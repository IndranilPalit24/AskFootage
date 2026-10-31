"""When a failed perception call still counts as spent (the cost rule)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from app_fakes import ScriptedPerception, track

from askfootage.adapters.meta.budget import LEDGER_FILE_NAME, HardCapBudget
from askfootage.application.budgeted_perception import BudgetedPerception
from askfootage.ports.budget import BudgetExceededError
from askfootage.ports.perception import PerceptionNotConfiguredError, PerceptionNotSentError


class Raises:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def detect_and_track(self, video_path, noun):
        raise self.error


def _run(tmp_path: Path, inner, cost="0.4"):
    budget = HardCapBudget(Decimal("1"), tmp_path)
    wrapped = BudgetedPerception(inner, budget, Decimal(cost))
    return budget, wrapped


def test_failure_after_a_possible_send_is_recorded_as_spent(tmp_path: Path) -> None:
    budget, wrapped = _run(tmp_path, Raises(RuntimeError("socket died mid reply")))
    with pytest.raises(RuntimeError):
        wrapped.detect_and_track(Path("v"), "x")
    assert budget.spent == Decimal("0.4") and budget.remaining == Decimal("0.6")
    assert HardCapBudget(Decimal("1"), tmp_path).spent == Decimal("0.4")  # survives restart


@pytest.mark.parametrize(
    "error", [PerceptionNotConfiguredError(), PerceptionNotSentError("bad input")]
)
def test_failure_before_sending_is_released(tmp_path: Path, error: Exception) -> None:
    budget, wrapped = _run(tmp_path, Raises(error))
    with pytest.raises(type(error)):
        wrapped.detect_and_track(Path("v"), "x")
    assert budget.spent == Decimal("0") and budget.remaining == Decimal("1")


def test_success_is_written_to_the_ledger(tmp_path: Path) -> None:
    budget, wrapped = _run(tmp_path, ScriptedPerception({"x": [track(1, "x", range(3))]}))
    wrapped.detect_and_track(Path("v"), "x")
    lines = [
        json.loads(line)
        for line in (tmp_path / LEDGER_FILE_NAME).read_text(encoding="utf-8").splitlines()
    ]
    assert [(e["outcome"], e["estimate"]) for e in lines] == [("sent", "0.4")]


def test_second_run_is_refused_by_the_first_runs_spend(tmp_path: Path) -> None:
    _, first = _run(tmp_path, ScriptedPerception({}), cost="0.7")
    first.detect_and_track(Path("v"), "x")
    _, second = _run(tmp_path, ScriptedPerception({}), cost="0.7")
    with pytest.raises(BudgetExceededError):
        second.detect_and_track(Path("v"), "x")
