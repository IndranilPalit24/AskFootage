"""A perception that asks a Budget before each call, so paid work stops at the hard cap.

Each detect_and_track call reserves `cost_per_call` first (BudgetExceededError, and no call,
when that would pass the cap).

Cost rule for a call that raises. The estimate is released (nothing spent) only when the
failure happened before anything could be billed:
- BudgetError (never sent),
- PerceptionNotConfiguredError (no backend),
- PerceptionNotSentError (the adapter is certain no request left the machine).
Any other exception may have come after the service accepted, and billed, the request
(a dropped connection, a bad reply, a timeout), so the estimate is recorded as spent. That
errs on the side of the cap. A success is recorded too.

If the budget offers write_ledger (HardCapBudget does), each spend is also appended to its
ledger, outcome "sent" or "charged", which is how the cap carries over to later runs.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from askfootage.domain.tracks import Track
from askfootage.ports.budget import Budget, BudgetError
from askfootage.ports.perception import (
    Perception,
    PerceptionNotConfiguredError,
    PerceptionNotSentError,
)

LEDGER_PATH_LABEL = "perception"
_NOT_SENT = (BudgetError, PerceptionNotConfiguredError, PerceptionNotSentError)


class BudgetedPerception:
    """Perception decorator: authorize -> call -> record (or release if never sent)."""

    def __init__(self, inner: Perception, budget: Budget, cost_per_call: Decimal) -> None:
        self._inner = inner
        self._budget = budget
        self._cost = cost_per_call

    def _spend(self, outcome: str) -> None:
        self._budget.record(self._cost, reservation=self._cost)
        write = getattr(self._budget, "write_ledger", None)
        if write is not None:
            write(path=LEDGER_PATH_LABEL, estimate=self._cost, outcome=outcome)

    def detect_and_track(self, video_path: Path, noun: str) -> list[Track]:
        """Run the wrapped perception inside a reservation of the configured cost."""
        self._budget.authorize(self._cost)
        try:
            tracks = self._inner.detect_and_track(video_path, noun)
        except _NOT_SENT:
            self._budget.release(self._cost)
            raise
        except BaseException:
            self._spend("charged")
            raise
        self._spend("sent")
        return tracks
