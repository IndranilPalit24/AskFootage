"""ingest_video(), add_video_concept() and BudgetedPerception against fakes."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from app_fakes import FakePreparer, MemoryTracks, ScriptedPerception, track

from askfootage.adapters.meta.budget import HardCapBudget
from askfootage.adapters.storage.local_files import LocalVideoFiles
from askfootage.application.add_concept import add_video_concept
from askfootage.application.budgeted_perception import BudgetedPerception
from askfootage.application.errors import (
    IndexingFailedError,
    IndexingNotConfiguredError,
    InvalidInputError,
    NotFoundError,
)
from askfootage.application.ingest_video import (
    IngestBudgetError,
    IngestServices,
    VideoPrepareFailedError,
    ingest_video,
)
from askfootage.ports.perception import PerceptionNotConfiguredError

SOURCE = Path("clip.mp4")


class NotConfigured:
    def detect_and_track(self, video_path: Path, noun: str) -> list:
        raise PerceptionNotConfiguredError()


def _services(tmp_path: Path, perception=None, cap: str = "10", preparer=None):
    budget = HardCapBudget(Decimal(cap), tmp_path / "ledger")
    perception = perception or ScriptedPerception(
        {
            "person": [track(1, "person", range(0, 10)), track(2, "person", range(12, 20), 20)],
            "cardboard box": [track(1, "cardboard box", range(0, 20))],
        }
    )
    tracks = MemoryTracks()
    preparer = preparer or FakePreparer()
    services = IngestServices(
        perception=perception,
        preparer=preparer,
        layout=LocalVideoFiles(tmp_path / "data"),
        tracks=tracks,
        budget=budget,
        cost_per_concept=Decimal("1"),
    )
    return services, perception, tracks, preparer, budget


def test_ingest_prepares_stitches_and_stores(tmp_path: Path) -> None:
    services, perception, tracks, preparer, budget = _services(tmp_path)
    result = ingest_video(services, "vid-1", SOURCE, ["person", "cardboard box"])
    assert preparer.calls == 1
    assert [n for _, n in perception.calls] == ["person", "cardboard box"]
    # the two person fragments were stitched into one track
    assert len(tracks.tracks_for("vid-1", "person")) == 1
    assert result.track_counts == {"person": 1, "cardboard box": 1}
    assert result.skipped == ()
    assert budget.spent == Decimal("2")


def test_reingest_is_idempotent_and_free(tmp_path: Path) -> None:
    services, perception, tracks, preparer, budget = _services(tmp_path)
    ingest_video(services, "vid-1", SOURCE, ["person", "cardboard box"])
    again = ingest_video(services, "vid-1", SOURCE, ["person", "cardboard box"])
    assert again.skipped == ("person", "cardboard box")
    assert len(perception.calls) == 2
    assert preparer.calls == 1
    assert budget.spent == Decimal("2")


def test_force_reruns(tmp_path: Path) -> None:
    services, perception, *_ = _services(tmp_path)
    ingest_video(services, "vid-1", SOURCE, ["person"])
    ingest_video(services, "vid-1", SOURCE, ["person"], force=True)
    assert len(perception.calls) == 2


def test_duplicate_and_blank_concepts(tmp_path: Path) -> None:
    services, perception, *_ = _services(tmp_path)
    ingest_video(services, "vid-1", SOURCE, [" person ", "person"])
    assert len(perception.calls) == 1
    with pytest.raises(InvalidInputError):
        ingest_video(services, "vid-1", SOURCE, ["  "])
    with pytest.raises(InvalidInputError):
        ingest_video(services, "vid-1", SOURCE, [])
    with pytest.raises(InvalidInputError):
        ingest_video(services, "bad/id", SOURCE, ["person"])


def test_budget_refusal_is_typed_and_keeps_earlier_work(tmp_path: Path) -> None:
    services, perception, tracks, _, budget = _services(tmp_path, cap="1")
    with pytest.raises(IngestBudgetError) as caught:
        ingest_video(services, "vid-1", SOURCE, ["person", "cardboard box"])
    assert "cap" in caught.value.message
    assert tracks.tracks_for("vid-1", "person")
    assert len(perception.calls) == 1
    assert budget.spent == Decimal("1")


def test_failed_perception_is_charged_because_it_may_have_been_billed(tmp_path: Path) -> None:
    perception = ScriptedPerception({}, fail_on=["person"])
    services, _, tracks, _, budget = _services(tmp_path, perception=perception)
    with pytest.raises(IndexingFailedError) as caught:
        ingest_video(services, "vid-1", SOURCE, ["person"])
    assert "secret" not in caught.value.message and "C:" not in caught.value.message
    assert budget.spent == Decimal("1") and budget.remaining == Decimal("9")
    assert tracks.saves == []


def test_not_configured_and_prepare_failure(tmp_path: Path) -> None:
    services, *_ = _services(tmp_path, perception=NotConfigured())
    with pytest.raises(IndexingNotConfiguredError):
        ingest_video(services, "vid-1", SOURCE, ["person"])
    services, *_ = _services(tmp_path / "b", preparer=FakePreparer(fail=True))
    with pytest.raises(VideoPrepareFailedError):
        ingest_video(services, "vid-1", SOURCE, ["person"])


def test_no_budget_is_allowed(tmp_path: Path) -> None:
    services, *_ = _services(tmp_path)
    free = IngestServices(services.perception, services.preparer, services.layout, services.tracks)
    assert ingest_video(free, "vid-1", SOURCE, ["person"]).track_counts == {"person": 1}


def test_add_concept_only_runs_new_concept(tmp_path: Path) -> None:
    services, perception, tracks, preparer, budget = _services(tmp_path)
    ingest_video(services, "vid-1", SOURCE, ["person"])
    result = add_video_concept(services, "vid-1", "cardboard box")
    assert [n for _, n in perception.calls] == ["person", "cardboard box"]
    assert preparer.calls == 1
    assert result.track_counts == {"cardboard box": 1}
    assert len(tracks.tracks_for("vid-1", "person")) == 1
    assert add_video_concept(services, "vid-1", "cardboard box").skipped == ("cardboard box",)
    assert len(perception.calls) == 2


def test_add_concept_needs_ingested_video(tmp_path: Path) -> None:
    services, *_ = _services(tmp_path)
    with pytest.raises(NotFoundError):
        add_video_concept(services, "never", "person")
    with pytest.raises(InvalidInputError):
        add_video_concept(services, "never", " ")


def test_budgeted_perception_passes_through(tmp_path: Path) -> None:
    budget = HardCapBudget(Decimal("1"), tmp_path / "l")
    inner = ScriptedPerception({"x": [track(1, "x", range(3))]})
    wrapped = BudgetedPerception(inner, budget, Decimal("0.4"))
    assert len(wrapped.detect_and_track(Path("v"), "x")) == 1
    assert budget.spent == Decimal("0.4")
