"""The hard spend cap under concurrent callers, offline.

Threads start together behind a barrier, and the thread switch interval is shortened so
that any unguarded read-then-write in the budget is very likely to be interleaved.
"""

import json
import sys
import threading
import time
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from askfootage.adapters.meta.budget import LEDGER_FILE_NAME, BudgetedTransport, HardCapBudget
from askfootage.adapters.meta.transport import MetaApiError, MetaRequest, RawResponse
from askfootage.ports.budget import BudgetExceededError

REQUEST = MetaRequest("/responses", json_body={"input": "hello"})
THREADS = 20
ESTIMATE = Decimal("0.01")
CAP = Decimal("0.10")


@pytest.fixture(autouse=True)
def _frequent_thread_switches() -> Iterator[None]:
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(previous)


class SlowTransport:
    """Takes a while to answer, so many calls are in flight at once; counts what it sends."""

    def __init__(self, fail_every: int = 0) -> None:
        self._lock = threading.Lock()
        self._fail_every = fail_every
        self.sent = 0

    def send(self, request: MetaRequest) -> RawResponse:
        """Count the call, wait, then answer 200 (or fail every `fail_every`-th call)."""
        with self._lock:
            self.sent += 1
            number = self.sent
        time.sleep(0.005)
        if self._fail_every and number % self._fail_every == 0:
            raise MetaApiError(500, "server error")
        return RawResponse(200, "{}")


def _run_together(count: int, work: Callable[[], None]) -> list[BaseException]:
    barrier = threading.Barrier(count)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        try:
            work()
        except BaseException as error:  # collected here and checked by the test
            with errors_lock:
                errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


def _sent_lines(ledger_dir: Path) -> int:
    text = (ledger_dir / LEDGER_FILE_NAME).read_text(encoding="utf-8")
    return sum(json.loads(line)["outcome"] == "sent" for line in text.splitlines())


@pytest.mark.parametrize("round_number", range(5))
def test_concurrent_callers_never_jointly_exceed_the_cap(tmp_path: Path, round_number: int) -> None:
    inner = SlowTransport()
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    transport = BudgetedTransport(inner, budget, lambda _request: ESTIMATE)

    errors = _run_together(THREADS, lambda: transport.send(REQUEST) and None)

    assert all(isinstance(error, BudgetExceededError) for error in errors), errors
    assert budget.spent <= CAP
    assert inner.sent == 10
    assert len(errors) == THREADS - 10
    assert budget.spent == ESTIMATE * inner.sent
    assert _sent_lines(tmp_path / "ledger") == inner.sent
    assert budget.remaining == Decimal(0)


def test_concurrent_failures_release_their_reservations(tmp_path: Path) -> None:
    inner = SlowTransport(fail_every=2)
    budget = HardCapBudget(Decimal("1.00"), tmp_path / "ledger")
    transport = BudgetedTransport(inner, budget, lambda _request: ESTIMATE)

    errors = _run_together(THREADS, lambda: transport.send(REQUEST) and None)

    assert inner.sent == THREADS
    assert len(errors) == THREADS // 2
    assert all(isinstance(error, MetaApiError) for error in errors)
    assert budget.spent == ESTIMATE * (THREADS // 2)
    assert budget.remaining == Decimal("1.00") - budget.spent
    assert _sent_lines(tmp_path / "ledger") == THREADS // 2


def test_hammering_the_budget_directly_keeps_it_exact(tmp_path: Path) -> None:
    budget = HardCapBudget(Decimal("100"), tmp_path / "ledger")
    rounds = 300
    granted = [0]
    granted_lock = threading.Lock()

    def work() -> None:
        for _ in range(rounds):
            try:
                budget.authorize(Decimal("0.03"))
            except BudgetExceededError:
                continue
            budget.record(Decimal("0.03"), reservation=Decimal("0.03"))
            with granted_lock:
                granted[0] += 1

    errors = _run_together(THREADS, work)

    assert errors == []
    assert budget.spent <= Decimal("100")
    assert budget.spent == Decimal("0.03") * granted[0]
    assert granted[0] == 3333
    assert budget.remaining == Decimal("100") - budget.spent


class _YieldingDecimal(Decimal):
    """A Decimal whose additions pause, forcing a thread switch mid-way through authorize.

    Under the GIL the budget's check-then-reserve step is rarely interrupted on its own;
    this makes an unguarded version fail every time instead of once in a while.
    """

    def __radd__(self, other: object) -> Decimal:
        time.sleep(0.001)
        return Decimal.__add__(Decimal(self), other)  # type: ignore[arg-type]


def test_cap_holds_when_each_check_is_interrupted(tmp_path: Path) -> None:
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    granted = [0]
    granted_lock = threading.Lock()

    def work() -> None:
        try:
            budget.authorize(_YieldingDecimal("0.01"))
        except BudgetExceededError:
            return
        with granted_lock:
            granted[0] += 1

    errors = _run_together(THREADS, work)

    assert errors == []
    assert granted[0] == 10
    assert budget.remaining == Decimal(0)
