"""The cap covers every run that shares a ledger, not each run alone."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from askfootage.adapters.meta.budget import LEDGER_FILE_NAME, HardCapBudget
from askfootage.ports.budget import BudgetExceededError


def _spend(budget: HardCapBudget, amount: str) -> None:
    budget.authorize(Decimal(amount))
    budget.record(Decimal(amount), reservation=Decimal(amount))
    budget.write_ledger(path="/x", estimate=Decimal(amount), outcome="sent")


def test_second_budget_starts_from_first_runs_spend(tmp_path: Path) -> None:
    first = HardCapBudget(Decimal("1.00"), tmp_path)
    _spend(first, "0.70")
    second = HardCapBudget(Decimal("1.00"), tmp_path)
    assert second.spent == Decimal("0.70")
    with pytest.raises(BudgetExceededError):
        second.authorize(Decimal("0.40"))
    _spend(second, "0.30")
    assert HardCapBudget(Decimal("1.00"), tmp_path).remaining == Decimal("0")


def test_only_spend_outcomes_count(tmp_path: Path) -> None:
    first = HardCapBudget(Decimal("5"), tmp_path)
    for outcome in ("refused", "failed", "no_estimate", "http_500"):
        first.write_ledger(path="/x", estimate=Decimal("1"), outcome=outcome)
    first.write_ledger(path="/x", estimate=Decimal("0.5"), outcome="charged")
    assert HardCapBudget(Decimal("5"), tmp_path).spent == Decimal("0.5")


def test_corrupt_ledger_lines_are_skipped_not_fatal(tmp_path: Path) -> None:
    ledger = tmp_path / LEDGER_FILE_NAME
    good = '{"outcome": "sent", "estimate": "0.25"}\n'
    ledger.write_bytes(
        good.encode()
        + b"\n{not json\n\xff\xfe\n[1]\n"
        + b'{"outcome": "sent", "estimate": "abc"}\n{"outcome": "sent"}\n'
        + b'{"outcome": "sent", "estimate": "-3"}\n'
        + good.encode().rstrip(b"\n")  # last line cut short of its newline
    )
    budget = HardCapBudget(Decimal("5"), tmp_path)
    assert budget.spent == Decimal("0.50")
    budget.write_ledger(path="/x", estimate=Decimal("1"), outcome="sent")
    assert HardCapBudget(Decimal("5"), tmp_path).spent == Decimal("1.50")


def test_unreadable_ledger_means_zero_prior_spend(tmp_path: Path) -> None:
    assert HardCapBudget(Decimal("1"), tmp_path / "fresh").spent == Decimal("0")
