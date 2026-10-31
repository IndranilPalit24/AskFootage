"""A hard spend cap on paid Meta API calls, and a transport that enforces it.

HardCapBudget implements the Budget port: it holds the cap it is given, the spend recorded
so far and the estimates reserved by calls still in flight, all under one lock, so
concurrent callers can never jointly authorize more than the cap. It also keeps an
append-only spend ledger.

BudgetedTransport wraps any Transport. For each request it asks an estimator for the cost,
reserves that estimate, sends, and records the estimate as spend only after a 2xx reply.
It fails closed: no estimate, no send. In dry-run mode it never sends; call
preview(request) to learn what a request would cost.

The ledger is the file LEDGER_FILE_NAME under the budget's ledger_dir: UTF-8 JSON lines
ending in LF, appended to and never rewritten. Each line describes one send attempt:

    {"time": "2026-10-31T12:00:00.000000+00:00", "run": "<hex id of this budget>",
     "method": "POST", "path": "/responses", "estimate": "0.18", "outcome": "sent",
     "spent_after": "0.18"}

`estimate` is null when none could be made. `outcome` is one of "sent" (2xx, spend
recorded), "refused" (over the cap, not sent), "no_estimate" (not sent), "failed" (the
transport raised; no spend) or "http_<status>" (a non-2xx reply; no spend). The path is
logged without any query string, and request bodies and headers are never logged.

Amounts are exact Decimals throughout; floats are refused.
"""

import json
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TypeGuard

from askfootage.adapters.meta.transport import MetaRequest, RawResponse, Transport
from askfootage.ports.budget import BudgetExceededError, MissingEstimateError

PRICE_PER_1000_FRAMES_USD = Decimal("0.20")
"""What the perception API charges per 1,000 video frames, in US dollars."""

MIN_FRAMES_PER_REQUEST = 50
"""Every request is billed for at least this many frames."""

LEDGER_FILE_NAME = "spend-ledger.jsonl"
"""Name of the spend ledger inside the budget's ledger_dir."""

_LEDGER_METHOD = "POST"  # every Meta API call is a POST (see client.py)
_ZERO = Decimal(0)


def frames_cost(frames: int) -> Decimal:
    """Exact dollar cost of a request covering `frames` frames, billed at least the minimum.

    frames_cost(900) is Decimal("0.18"); frames_cost(20) is billed as 50 frames,
    Decimal("0.01"). Raises TypeError for a non-integer and ValueError for a negative count.
    """
    if not isinstance(frames, int) or isinstance(frames, bool):
        raise TypeError(f"frames must be an int; got {type(frames).__name__}")
    if frames < 0:
        raise ValueError(f"frames must not be negative; got {frames}")
    return Decimal(max(MIN_FRAMES_PER_REQUEST, frames)) * PRICE_PER_1000_FRAMES_USD / 1000


def _is_usable_amount(value: object) -> TypeGuard[Decimal]:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


class DryRunSendError(RuntimeError):
    """send() was called on a BudgetedTransport in dry-run mode; nothing was sent."""


class HardCapBudget:
    """A thread-safe hard spend cap for one run, with an append-only ledger.

    `cap` is the most the run may spend, in dollars, as a finite, non-negative Decimal;
    the caller supplies it (usually Settings.max_run_cost_usd). Spend starts at zero for
    each new budget. `ledger_dir` is created if missing, and the ledger file in it is
    created up front, so an unwritable ledger is found before any call is made.
    """

    def __init__(self, cap: Decimal, ledger_dir: Path) -> None:
        if not isinstance(cap, Decimal):
            raise TypeError(f"cap must be a Decimal; got {type(cap).__name__}")
        if not _is_usable_amount(cap):
            raise ValueError("cap must be a finite, non-negative amount")
        self._cap = cap
        self._spent = _ZERO
        self._reserved = _ZERO
        self._lock = threading.Lock()
        self._run_id = uuid.uuid4().hex
        ledger_dir.mkdir(parents=True, exist_ok=True)
        self._ledger_path = ledger_dir / LEDGER_FILE_NAME
        with self._ledger_path.open("ab"):
            pass

    @property
    def cap(self) -> Decimal:
        """The most this run may spend, in dollars."""
        return self._cap

    @property
    def spent(self) -> Decimal:
        """What successful calls have recorded so far, in dollars."""
        with self._lock:
            return self._spent

    @property
    def remaining(self) -> Decimal:
        """What is left to authorize: the cap less recorded spend and in-flight reservations."""
        with self._lock:
            return max(self._cap - self._spent - self._reserved, _ZERO)

    def authorize(self, estimate: Decimal) -> None:
        """Reserve `estimate` dollars, or raise; see the Budget port for the rules."""
        if not _is_usable_amount(estimate):
            raise MissingEstimateError(
                "Refused: the call's cost estimate is not a finite, non-negative Decimal"
            )
        with self._lock:
            if self._spent + self._reserved + estimate > self._cap:
                raise BudgetExceededError(
                    spent=self._spent,
                    estimate=estimate,
                    cap=self._cap,
                    in_flight=self._reserved,
                )
            self._reserved += estimate

    def record(self, cost: Decimal, *, reservation: Decimal = _ZERO) -> None:
        """Add `cost` to the spend and free `reservation`, in one step under the lock."""
        if not (_is_usable_amount(cost) and _is_usable_amount(reservation)):
            raise ValueError("cost and reservation must be finite, non-negative Decimals")
        with self._lock:
            self._check_reserved(reservation)
            self._reserved -= reservation
            self._spent += cost

    def release(self, reservation: Decimal) -> None:
        """Free a reservation whose call failed, adding nothing to the spend."""
        if not _is_usable_amount(reservation):
            raise ValueError("reservation must be a finite, non-negative Decimal")
        with self._lock:
            self._check_reserved(reservation)
            self._reserved -= reservation

    def _check_reserved(self, reservation: Decimal) -> None:
        # Freeing more than is held would hand the surplus to later callers.
        if reservation > self._reserved:
            raise ValueError("cannot free more than is currently reserved")

    def write_ledger(self, *, path: str, estimate: Decimal | None, outcome: str) -> None:
        """Append one line for one send attempt, stamped with the spend after it.

        `path` is the request path; anything from "?" on is dropped. Written under the
        budget's lock, so lines never interleave; spent_after is the run's total recorded
        spend at the moment the line is written.
        """
        with self._lock:
            entry = {
                "time": datetime.now(UTC).isoformat(),
                "run": self._run_id,
                "method": _LEDGER_METHOD,
                "path": path.split("?", 1)[0],
                "estimate": None if estimate is None else str(estimate),
                "outcome": outcome,
                "spent_after": str(self._spent),
            }
            line = json.dumps(entry, ensure_ascii=False) + "\n"
            with self._ledger_path.open("ab") as ledger:
                ledger.write(line.encode("utf-8"))


class BudgetedTransport:
    """A Transport that sends through `inner` only within `budget`'s hard cap.

    `estimator` returns a request's cost in dollars as a Decimal, or None when it cannot
    tell; None, an exception or an unusable value refuses the request (fails closed).
    The estimate is reserved before sending and recorded as spend only after a 2xx reply;
    a MetaError, any other exception or a non-2xx reply frees the reservation and adds
    nothing. Non-2xx replies are returned unchanged.

    With dry_run=True nothing is ever sent: preview(request) returns the estimate, and
    send() raises DryRunSendError.
    """

    def __init__(
        self,
        inner: Transport,
        budget: HardCapBudget,
        estimator: Callable[[MetaRequest], Decimal | None],
        dry_run: bool = False,
    ) -> None:
        self._inner = inner
        self._budget = budget
        self._estimator = estimator
        self._dry_run = dry_run

    @property
    def dry_run(self) -> bool:
        """True when this transport never sends, and only previews costs."""
        return self._dry_run

    def preview(self, request: MetaRequest) -> Decimal:
        """Return what `request` is estimated to cost, without sending or reserving anything.

        Works in either mode. Raises MissingEstimateError when no usable estimate exists.
        """
        return self._estimate(request)

    def send(self, request: MetaRequest) -> RawResponse:
        """Authorize, send and record `request`; see the class docstring for the rules.

        Raises DryRunSendError in dry-run mode, MissingEstimateError when the cost cannot
        be estimated and BudgetExceededError when it would pass the cap; in all three
        cases nothing is sent.
        """
        if self._dry_run:
            raise DryRunSendError(
                "This transport is in dry run mode and never sends; use preview(request)"
            )
        try:
            estimate = self._estimate(request)
        except MissingEstimateError:
            self._budget.write_ledger(path=request.path, estimate=None, outcome="no_estimate")
            raise
        try:
            self._budget.authorize(estimate)
        except BudgetExceededError:
            self._budget.write_ledger(path=request.path, estimate=estimate, outcome="refused")
            raise

        try:
            reply = self._inner.send(request)
        except BaseException:
            self._budget.release(estimate)
            self._budget.write_ledger(path=request.path, estimate=estimate, outcome="failed")
            raise

        if 200 <= reply.status < 300:
            self._budget.record(estimate, reservation=estimate)
            outcome = "sent"
        else:
            self._budget.release(estimate)
            outcome = f"http_{reply.status}"
        self._budget.write_ledger(path=request.path, estimate=estimate, outcome=outcome)
        return reply

    def _estimate(self, request: MetaRequest) -> Decimal:
        try:
            estimate = self._estimator(request)
        except Exception as error:
            failure = type(error).__name__
        else:
            if _is_usable_amount(estimate):
                return estimate
            failure = "no usable estimate" if estimate is None else "an unusable estimate"
        # Raised outside the except block, and from None, so the estimator's own error
        # (which may quote a request or a local path) is not chained onto this one.
        raise MissingEstimateError(
            f"Refused: the call's cost could not be estimated ({failure})"
        ) from None
