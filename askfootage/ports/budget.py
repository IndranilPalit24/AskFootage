"""Port for a spend budget: a hard cap on what one run may spend on paid API calls.

A caller asks the budget to authorize a call's estimated cost before making the call, and
records the cost once the call has succeeded. Amounts are US dollars as exact Decimals,
never floats. Error messages state amounts only: no keys, no request bodies, no paths.

Standard library only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

_CENT = Decimal("0.01")


def format_dollars(amount: Decimal) -> str:
    """Show `amount` as dollars: two decimals, or as many as it needs to stay exact.

    Decimal("0.5") gives "$0.50"; Decimal("0.0102") gives "$0.0102", so a sub-cent
    estimate is never rounded into a message that reads as if it fits under the cap.
    """
    if amount == amount.quantize(_CENT):
        return f"${amount.quantize(_CENT)}"
    return f"${amount.normalize():f}"


class BudgetError(Exception):
    """Base class for every refusal by a budget. Messages are safe to log or show."""


class BudgetExceededError(BudgetError):
    """Authorizing an estimate would take the committed spend past the cap.

    `spent` is what has already been recorded, `in_flight` what other authorized calls
    still hold in reserve, `estimate` the refused call's estimate and `cap` the limit.
    The call was not made.
    """

    def __init__(
        self,
        *,
        spent: Decimal,
        estimate: Decimal,
        cap: Decimal,
        in_flight: Decimal = Decimal(0),
    ) -> None:
        self.spent = spent
        self.estimate = estimate
        self.cap = cap
        self.in_flight = in_flight
        held = f" (+ {format_dollars(in_flight)} in flight)" if in_flight else ""
        super().__init__(
            f"{format_dollars(spent)} spent{held} + {format_dollars(estimate)} estimated "
            f"would exceed the {format_dollars(cap)} cap"
        )


class MissingEstimateError(BudgetError):
    """A call's cost could not be estimated, so it was refused: the budget fails closed."""


class Budget(Protocol):
    """A hard spend cap shared by every paid call in one run. Implementations are thread-safe.

    Each call goes: authorize(estimate) before sending; then, on success,
    record(cost, reservation=estimate), or, on failure, release(estimate).
    """

    @property
    def cap(self) -> Decimal:
        """The most this run may spend, in dollars."""

    @property
    def spent(self) -> Decimal:
        """What successful calls have recorded so far, in dollars."""

    @property
    def remaining(self) -> Decimal:
        """What is left to authorize: the cap less recorded spend and in-flight reservations."""

    def authorize(self, estimate: Decimal) -> None:
        """Reserve `estimate` dollars for one call, or refuse.

        Allowed when spent + in-flight + estimate is at most the cap (exactly at the cap
        is allowed). Raises BudgetExceededError otherwise, and MissingEstimateError when
        `estimate` is not a finite, non-negative Decimal; a refused call reserves nothing.
        """

    def record(self, cost: Decimal, *, reservation: Decimal = Decimal(0)) -> None:
        """Add `cost` to the spend and, in the same step, free `reservation` from in-flight."""

    def release(self, reservation: Decimal) -> None:
        """Free a reservation whose call failed, adding nothing to the spend."""
