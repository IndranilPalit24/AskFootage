"""ingest_video / add_video_concept: cost, normalising, frame size, re-ingest, empty marker."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest
from app_fakes import FakePreparer, ScriptedPerception, track

from askfootage.adapters.fake.perception import CopyPreparer
from askfootage.adapters.meta.budget import HardCapBudget, frames_cost
from askfootage.adapters.storage.json_tracks import JsonTrackStore
from askfootage.adapters.storage.local_files import LocalVideoFiles
from askfootage.application.add_concept import add_video_concept
from askfootage.application.errors import IndexingNotConfiguredError, InvalidInputError
from askfootage.application.ingest_video import (
    IngestServices,
    SourceChangedError,
    clean_concepts,
    ingest_video,
)
from askfootage.ports.video_store import PreparedVideo


class SizedPreparer(FakePreparer):
    def __init__(self, frames=900, size=(640, 360)):
        super().__init__()
        self.frames, self.size = frames, size

    def prepare(self, source, dest_dir):
        super().prepare(source, dest_dir)
        return PreparedVideo(
            dest_dir / "prepared.mp4", 5.0, self.frames / 5, self.frames, *self.size
        )


class Unconfigured(ScriptedPerception):
    configured = False


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video-v1")
    return path


def _rig(tmp_path: Path, preparer=None, perception=None, cap="10", **extra):
    layout = LocalVideoFiles(tmp_path / "data")
    tracks = JsonTrackStore(layout)
    perception = perception or ScriptedPerception({"person": [track(1, "person", range(5))]})
    budget = HardCapBudget(Decimal(cap), tmp_path / "ledger")
    preparer = preparer or SizedPreparer()
    services = IngestServices(
        perception=perception,
        preparer=preparer,
        layout=layout,
        tracks=tracks,
        budget=budget,
        estimate_cost=frames_cost,
        **extra,
    )
    return services, perception, tracks, preparer, budget


# --- 2 cost from frame count ---------------------------------------------------------------


def test_cost_comes_from_the_prepared_frame_count(tmp_path: Path, source: Path) -> None:
    services, _, _, _, budget = _rig(tmp_path, SizedPreparer(frames=900))
    ingest_video(services, "v", source, ["person", "bag"])
    assert budget.spent == 2 * frames_cost(900)


def test_override_cannot_lower_a_real_estimate(tmp_path: Path, source: Path) -> None:
    services, _, _, _, budget = _rig(
        tmp_path, SizedPreparer(frames=900), cost_per_concept=Decimal("0.01")
    )
    ingest_video(services, "v", source, ["person"])
    assert budget.spent == frames_cost(900)


def test_override_may_raise_the_estimate(tmp_path: Path, source: Path) -> None:
    services, _, _, _, budget = _rig(
        tmp_path, SizedPreparer(frames=900), cost_per_concept=Decimal("0.50")
    )
    ingest_video(services, "v", source, ["person"])
    assert budget.spent == Decimal("0.50")


def test_add_concept_prices_from_the_recorded_frame_count(tmp_path: Path, source: Path) -> None:
    services, _, _, _, budget = _rig(tmp_path, SizedPreparer(frames=4000))
    ingest_video(services, "v", source, ["person"])
    add_video_concept(services, "v", "bag")
    assert budget.spent == 2 * frames_cost(4000)


# --- 6 normalising -------------------------------------------------------------------------


def test_concepts_are_casefolded_and_deduplicated() -> None:
    assert clean_concepts(["  Person ", "PERSON", "Cardboard   Box"]) == [
        "person",
        "cardboard box",
    ]


def test_concepts_are_stored_under_their_normalised_name(tmp_path: Path, source: Path) -> None:
    services, _, tracks, _, _ = _rig(tmp_path)
    result = ingest_video(services, "v", source, ["Forklift", "person"])
    assert result.track_counts.keys() == {"forklift", "person"}
    assert tracks.concept_done("v", "forklift")


# --- 8 frame size --------------------------------------------------------------------------


def test_frame_size_and_prepared_info_are_recorded(tmp_path: Path, source: Path) -> None:
    services, _, tracks, _, _ = _rig(tmp_path, SizedPreparer(frames=300, size=(1280, 720)))
    ingest_video(services, "v", source, ["person"])
    assert tracks.frame_size("v") == (1280, 720)
    assert tracks.prepared_info("v")[0] == 300


def test_fake_preparer_supplies_a_default_frame_size(tmp_path: Path, source: Path) -> None:
    services, _, tracks, _, _ = _rig(tmp_path, CopyPreparer())
    ingest_video(services, "v", source, ["person"])
    size = tracks.frame_size("v")
    assert size is not None and size[0] > 0 and size[1] > 0


# --- 10 re-ingest --------------------------------------------------------------------------


def test_prepared_copy_is_written_atomically_without_leftovers(
    tmp_path: Path, source: Path
) -> None:
    services, _, _, _, _ = _rig(tmp_path)
    ingest_video(services, "v", source, ["person"])
    names = sorted(p.name for p in (tmp_path / "data" / "v").iterdir())
    assert names == ["prepared.mp4", "tracks.json"]


def test_copy_preparer_leaves_no_temp_files(tmp_path: Path, source: Path) -> None:
    CopyPreparer().prepare(source, tmp_path / "out")
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["prepared.mp4"]


def test_changed_source_is_refused_without_force_and_redone_with_it(
    tmp_path: Path, source: Path
) -> None:
    services, perception, _, preparer, _ = _rig(tmp_path)
    ingest_video(services, "v", source, ["person"])
    source.write_bytes(b"video-v2-longer")
    os.utime(source, ns=(1, 1))
    with pytest.raises(SourceChangedError) as caught:
        ingest_video(services, "v", source, ["person", "bag"])
    assert "--force" in caught.value.message and str(tmp_path) not in caught.value.message
    assert preparer.calls == 1 and len(perception.calls) == 1
    ingest_video(services, "v", source, ["person"], force=True)
    assert preparer.calls == 2
    ingest_video(services, "v", source, ["person"])  # fingerprint refreshed


def test_unchanged_source_reuses_the_copy(tmp_path: Path, source: Path) -> None:
    services, _, _, preparer, _ = _rig(tmp_path)
    ingest_video(services, "v", source, ["person"])
    ingest_video(services, "v", source, ["person", "bag"])
    assert preparer.calls == 1


# --- 16 ran-empty marker -------------------------------------------------------------------


def test_a_concept_that_found_nothing_is_not_billed_again(tmp_path: Path, source: Path) -> None:
    services, perception, _, _, budget = _rig(tmp_path)
    ingest_video(services, "v", source, ["bag"])
    spent = budget.spent
    again = ingest_video(services, "v", source, ["bag"])
    assert again.skipped == ("bag",) and budget.spent == spent and len(perception.calls) == 1
    add = add_video_concept(services, "v", "bag")
    assert add.skipped == ("bag",) and len(perception.calls) == 1


# --- 17 configured check -------------------------------------------------------------------


def test_unconfigured_perception_fails_before_preparing(tmp_path: Path, source: Path) -> None:
    services, _, _, preparer, _ = _rig(tmp_path, perception=Unconfigured({}))
    with pytest.raises(IndexingNotConfiguredError):
        ingest_video(services, "v", source, ["person"])
    assert preparer.calls == 0


# --- 15 read paths make no folders ---------------------------------------------------------


def test_add_concept_on_an_unknown_video_creates_no_folder(tmp_path: Path) -> None:
    services, *_ = _rig(tmp_path)
    with pytest.raises(Exception, match="not been ingested"):
        add_video_concept(services, "ghost", "bag")
    assert not (tmp_path / "data" / "ghost").exists()


def test_bad_id_is_still_invalid_input(tmp_path: Path) -> None:
    services, *_ = _rig(tmp_path)
    with pytest.raises(InvalidInputError):
        add_video_concept(services, "../x", "bag")
