"""The default run cap is $25 and a run is refused past it."""

from decimal import Decimal
from pathlib import Path

import pytest

from askfootage.adapters.meta.budget import HardCapBudget, frames_cost
from askfootage.ports.budget import BudgetError, BudgetExceededError
from askfootage.settings import Settings


def test_default_cap_is_25_dollars_and_refuses_past_it(tmp_path: Path) -> None:
    cap = Settings(_env_file=None).max_run_cost_usd  # type: ignore[call-arg]
    assert cap == Decimal("25")
    budget = HardCapBudget(cap, tmp_path)
    budget.authorize(Decimal("25"))
    with pytest.raises(BudgetExceededError) as info:
        budget.authorize(Decimal("0.01"))
    assert isinstance(info.value, BudgetError)


def test_frame_cost_estimate_is_twenty_cents_per_thousand_frames() -> None:
    assert frames_cost(1000) == Decimal("0.20")
    assert frames_cost(125_000) == Decimal("25.00")
