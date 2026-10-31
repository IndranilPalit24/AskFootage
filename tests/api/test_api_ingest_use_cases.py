"""The indexing use cases on their own: start, run after the reply, and add a concept.

No HTTP here: start_indexing, run_indexing and add_concept are called directly with the
in-memory library and the indexing fakes. Nothing touches disk, the network or Meta.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

import pytest
from api_fakes import (
    FAKE_SERVER_ROOT,
    REPO_ROOT,
    FakeLayout,
    FakePerception,
    FakePreparer,
    InMemoryLibrary,
    InMemoryTrackStore,
    make_track,
)
from api_support import FAKE_KEY

from askfootage.application import add_concept as concepts
from askfootage.application.errors import (
    IndexingFailedError,
    IndexingNotConfiguredError,
    InvalidInputError,
    NotFoundError,
    RecordingNotReadyError,
    RecordingNotWaitingError,
)
from askfootage.application.ingest_video import IndexingPipeline, run_indexing, start_indexing
from askfootage.application.library import Library
from askfootage.ports.library_store import Recording
from askfootage.ports.perception import (
    NOT_CONFIGURED_MESSAGE,
    PerceptionError,
    PerceptionNotConfiguredError,
)
from askfootage.ports.video_store import VideoPreparationError

WAITING = "rec-1030-1200"
READY = "rec-1030-0800"
INDEXING = "rec-1030-cam2-0800"
PREPARING = "rec-1030-1000"
NOUNS = ("person", "cardboard box")
SOURCE = Path(FAKE_SERVER_ROOT / "uploads" / "rec-1030-1200.mp4")
LEAKY_TEXT = f"failed reading C:\\Users\\someone\\data\\x.mp4 with key={FAKE_KEY}"
"""Exception text that must never reach a status note or the log."""
FORBIDDEN_IN_NOTES = (FAKE_KEY, "sk-test", "C:\\Users", str(FAKE_SERVER_ROOT), "Traceback")


class Rig:
    """The library, its fakes and a pipeline built from them."""

    def __init__(
        self,
        store: InMemoryLibrary,
        *,
        perception: FakePerception | None = None,
        preparer: FakePreparer | None = None,
        source: Path | None = SOURCE,
    ) -> None:
        self.store = store
        self.library = Library.from_store(store)
        self.tracks = InMemoryTrackStore(store)
        self.layout = FakeLayout()
        self.preparer = preparer or FakePreparer()
        self.perception = perception or FakePerception(
            {
                "person": [make_track(0, "person", [0, 1, 2]), make_track(1, "person", [5, 6])],
                "cardboard box": [make_track(0, "cardboard box", [1, 2])],
            }
        )
        self.source_calls: list[str] = []
        self.source = source
        self.pipeline = IndexingPipeline(
            perception=self.perception,
            preparer=self.preparer,
            layout=self.layout,
            tracks=self.tracks,
            nouns=NOUNS,
            source_for=self._source_for,
        )

    def _source_for(self, recording: Recording) -> Path | None:
        self.source_calls.append(recording.id)
        return self.source

    def status(self, recording_id: str) -> str:
        """The recording's stored status."""
        return self.store.recordings[recording_id].status

    def note(self, recording_id: str) -> str | None:
        """The recording's stored status note."""
        return self.store.recordings[recording_id].status_note

    def statuses(self, recording_id: str) -> list[str]:
        """Every status the recording was given, in order."""
        return [status for rid, status, _ in self.store.status_log if rid == recording_id]


@pytest.fixture
def rig(store: InMemoryLibrary) -> Rig:
    """The seeded library with a working pipeline."""
    return Rig(store)


def _start_and_run(rig: Rig, recording_id: str = WAITING) -> None:
    start_indexing(rig.library, rig.pipeline, recording_id)
    run_indexing(rig.library, rig.pipeline, recording_id)


def _assert_safe_note(note: str | None) -> None:
    assert note is not None and note.strip()
    assert len(note) <= 300
    for needle in FORBIDDEN_IN_NOTES:
        assert needle not in note
    assert "failed reading" not in note


# --- Starting -------------------------------------------------------------------------------


def test_start_moves_a_waiting_recording_to_preparing(rig: Rig) -> None:
    job = start_indexing(rig.library, rig.pipeline, WAITING)
    assert job.recording.id == WAITING and job.recording.status == "preparing"
    assert rig.store.status_log == [(WAITING, "preparing", None)]
    assert rig.preparer.calls == [] and rig.perception.calls == []
    job.run()
    assert rig.statuses(WAITING) == ["preparing", "indexing", "ready"]


def test_start_clears_the_note_left_by_a_failed_attempt(rig: Rig) -> None:
    rig.store.set_recording_status(WAITING, "waiting", note="An earlier attempt failed.")
    start_indexing(rig.library, rig.pipeline, WAITING)
    assert rig.status(WAITING) == "preparing"
    assert rig.note(WAITING) is None


def test_without_a_pipeline_nothing_is_looked_up_or_changed(store: InMemoryLibrary) -> None:
    library = Library.from_store(store)
    before = dict(store.recordings)
    for recording_id in (WAITING, READY, "rec-nope"):
        with pytest.raises(IndexingNotConfiguredError) as raised:
            start_indexing(library, None, recording_id)
        assert raised.value.message == NOT_CONFIGURED_MESSAGE
    assert store.recordings == before
    assert store.status_log == []


def test_start_on_an_unknown_recording_is_not_found(rig: Rig) -> None:
    with pytest.raises(NotFoundError):
        start_indexing(rig.library, rig.pipeline, "rec-nope")
    assert rig.store.status_log == []


@pytest.mark.parametrize("recording_id", [READY, INDEXING, PREPARING])
def test_start_refuses_a_recording_that_is_not_waiting(rig: Rig, recording_id: str) -> None:
    before = rig.store.recordings[recording_id]
    with pytest.raises(RecordingNotWaitingError):
        start_indexing(rig.library, rig.pipeline, recording_id)
    assert rig.store.recordings[recording_id] == before
    assert rig.store.status_log == []


def test_a_second_start_is_refused(rig: Rig) -> None:
    start_indexing(rig.library, rig.pipeline, WAITING)
    with pytest.raises(RecordingNotWaitingError):
        start_indexing(rig.library, rig.pipeline, WAITING)
    assert rig.statuses(WAITING) == ["preparing"]


class RacingLibrary(InMemoryLibrary):
    """Another caller starts the same recording between this caller's read and its write."""

    def get_recording(self, recording_id: str) -> Recording | None:
        found = super().get_recording(recording_id)
        if found is not None and found.status == "waiting":
            super().set_recording_status(recording_id, "preparing", expected="waiting")
        return found


def test_a_start_that_loses_the_race_is_refused() -> None:
    store = RacingLibrary.from_seed()
    rig = Rig(store)
    with pytest.raises(RecordingNotWaitingError):
        start_indexing(rig.library, rig.pipeline, WAITING)
    # Only the other caller's change happened.
    assert rig.statuses(WAITING) == ["preparing"]


class VanishingLibrary(InMemoryLibrary):
    """The recording is deleted between this caller's read and its write."""

    def get_recording(self, recording_id: str) -> Recording | None:
        found = super().get_recording(recording_id)
        self.recordings.pop(recording_id, None)
        return found


def test_a_recording_deleted_while_starting_is_not_found() -> None:
    rig = Rig(VanishingLibrary.from_seed())
    with pytest.raises(NotFoundError):
        start_indexing(rig.library, rig.pipeline, WAITING)


# --- Running --------------------------------------------------------------------------------


def test_a_run_goes_preparing_indexing_ready_and_saves_tracks_per_noun(rig: Rig) -> None:
    _start_and_run(rig)
    assert rig.statuses(WAITING) == ["preparing", "indexing", "ready"]
    assert rig.note(WAITING) is None
    assert rig.preparer.calls == [(SOURCE, rig.layout.video_dir(WAITING))]
    prepared = rig.layout.video_dir(WAITING) / "prepared.mp4"
    assert rig.perception.calls == [(prepared, "person"), (prepared, "cardboard box")]
    assert [track.track_id for track in rig.tracks.tracks_for(WAITING, "person")] == [0, 1]
    assert len(rig.tracks.tracks_for(WAITING, "cardboard box")) == 1
    assert rig.source_calls == [WAITING]


def test_perception_runs_only_after_the_status_is_indexing(rig: Rig) -> None:
    seen: list[str] = []
    original = rig.perception.detect_and_track

    def watching(video_path: Path, noun: str) -> list[Any]:
        seen.append(rig.status(WAITING))
        return original(video_path, noun)

    rig.perception.detect_and_track = watching  # type: ignore[method-assign]
    _start_and_run(rig)
    assert seen == ["indexing", "indexing"]


def test_the_working_copy_is_made_while_the_status_is_preparing(rig: Rig) -> None:
    seen: list[str] = []
    rig.preparer.on_prepare.append(lambda: seen.append(rig.status(WAITING)))
    _start_and_run(rig)
    assert seen == ["preparing"]


def test_a_noun_with_nothing_found_saves_an_empty_set(store: InMemoryLibrary) -> None:
    rig = Rig(store, perception=FakePerception({}))
    _start_and_run(rig)
    assert rig.status(WAITING) == "ready"
    assert rig.tracks.calls == [(WAITING, "person"), (WAITING, "cardboard box")]


def test_a_run_creates_no_clips(rig: Rig) -> None:
    clips_before = dict(rig.store.clips)
    _start_and_run(rig)
    assert rig.store.clips == clips_before


def test_a_run_does_nothing_unless_the_recording_is_preparing(rig: Rig) -> None:
    for recording_id in (WAITING, READY, INDEXING, "rec-nope"):
        run_indexing(rig.library, rig.pipeline, recording_id)
    assert rig.store.status_log == []
    assert rig.preparer.calls == [] and rig.perception.calls == []


def test_a_run_stops_quietly_when_the_recording_is_deleted_midway(rig: Rig) -> None:
    rig.preparer.on_prepare.append(lambda: rig.store.recordings.pop(WAITING))
    _start_and_run(rig)
    assert rig.perception.calls == []
    assert rig.statuses(WAITING) == ["preparing"]


def test_a_run_does_not_overwrite_a_status_someone_else_set(rig: Rig) -> None:
    rig.preparer.on_prepare.append(
        lambda: rig.store.set_recording_status(WAITING, "waiting", expected="preparing")
    )
    _start_and_run(rig)
    assert rig.perception.calls == []
    assert rig.statuses(WAITING) == ["preparing", "waiting"]


class FailingTracks(InMemoryTrackStore):
    """A track store whose writes fail with an exception holding a path and the key."""

    def save_tracks(self, video_id: str, concept: str, tracks: Any) -> None:
        raise RuntimeError(LEAKY_TEXT)


class FailingReady(InMemoryLibrary):
    """A store that cannot record the final ready status."""

    def set_recording_status(self, recording_id: str, status: Any, **kwargs: Any) -> Any:
        if status == "ready":
            raise RuntimeError(LEAKY_TEXT)
        return super().set_recording_status(recording_id, status, **kwargs)


def _failing_rig(store: InMemoryLibrary, stage: str) -> Rig:
    if stage == "source missing":
        return Rig(store, source=None)
    if stage == "source lookup raises":
        rig = Rig(store)

        def broken(recording: Recording) -> Path | None:
            raise OSError(LEAKY_TEXT)

        object.__setattr__(rig.pipeline, "source_for", broken)
        return rig
    if stage == "preparation fails":
        return Rig(store, preparer=FakePreparer(VideoPreparationError(LEAKY_TEXT)))
    if stage == "preparer crashes":
        return Rig(store, preparer=FakePreparer(ZeroDivisionError(LEAKY_TEXT)))
    if stage == "perception fails":
        return Rig(store, perception=FakePerception(error=PerceptionError(LEAKY_TEXT)))
    if stage == "perception fails on the second noun":
        perception = FakePerception(error=PerceptionError(LEAKY_TEXT), fail_on=["cardboard box"])
        return Rig(store, perception=perception)
    if stage == "perception crashes":
        return Rig(store, perception=FakePerception(error=KeyError(LEAKY_TEXT)))
    if stage == "perception returns the wrong label":
        wrong = FakePerception({"person": [make_track(0, "forklift", [0, 1])]})
        return Rig(store, perception=wrong)
    if stage == "saving tracks fails":
        rig = Rig(store)
        object.__setattr__(rig.pipeline, "tracks", FailingTracks(store))
        return rig
    raise AssertionError(stage)


STAGES = [
    ("source missing", "preparing"),
    ("source lookup raises", "preparing"),
    ("preparation fails", "preparing"),
    ("preparer crashes", "preparing"),
    ("perception fails", "indexing"),
    ("perception fails on the second noun", "indexing"),
    ("perception crashes", "indexing"),
    ("perception returns the wrong label", "indexing"),
    ("saving tracks fails", "indexing"),
]


@pytest.mark.parametrize(("stage", "failed_while"), STAGES)
def test_a_failure_in_any_stage_goes_back_to_waiting_with_a_safe_note(
    store: InMemoryLibrary, stage: str, failed_while: str
) -> None:
    rig = _failing_rig(store, stage)
    _start_and_run(rig)
    reached = ["preparing"] if failed_while == "preparing" else ["preparing", "indexing"]
    assert rig.statuses(WAITING) == [*reached, "waiting"]
    _assert_safe_note(rig.note(WAITING))


def test_a_failure_to_record_ready_goes_back_to_waiting() -> None:
    rig = Rig(FailingReady.from_seed())
    _start_and_run(rig)
    assert rig.statuses(WAITING) == ["preparing", "indexing", "waiting"]
    _assert_safe_note(rig.note(WAITING))


def test_each_stage_has_its_own_note() -> None:
    notes = set()
    for stage in ("source missing", "preparation fails", "perception fails", "saving tracks fails"):
        rig = _failing_rig(InMemoryLibrary.from_seed(), stage)
        _start_and_run(rig)
        notes.add(rig.note(WAITING))
    assert len(notes) == 4


def test_a_build_without_perception_says_so_in_the_note(store: InMemoryLibrary) -> None:
    rig = Rig(store, perception=FakePerception(error=PerceptionNotConfiguredError()))
    _start_and_run(rig)
    assert rig.status(WAITING) == "waiting"
    assert rig.note(WAITING) == f"{NOT_CONFIGURED_MESSAGE}."


def test_a_perception_message_never_reaches_the_note_even_if_it_claims_to_be_safe(
    store: InMemoryLibrary,
) -> None:
    rig = Rig(store, perception=FakePerception(error=PerceptionError("model said: try 42")))
    _start_and_run(rig)
    assert "model said" not in (rig.note(WAITING) or "")


def test_a_failed_run_can_be_started_again_and_then_succeeds(store: InMemoryLibrary) -> None:
    rig = Rig(store, preparer=FakePreparer(VideoPreparationError("bad file")))
    _start_and_run(rig)
    assert rig.status(WAITING) == "waiting"
    rig.preparer.error = None
    _start_and_run(rig)
    assert rig.status(WAITING) == "ready"
    assert rig.note(WAITING) is None


def test_a_failure_is_logged_by_stage_and_type_without_its_text(
    store: InMemoryLibrary, caplog: pytest.LogCaptureFixture
) -> None:
    rig = Rig(store, perception=FakePerception(error=PerceptionError(LEAKY_TEXT)))
    with caplog.at_level(logging.WARNING, logger="askfootage.indexing"):
        _start_and_run(rig)
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert WAITING in logged and "PerceptionError" in logged and "indexing" in logged
    for needle in FORBIDDEN_IN_NOTES:
        assert needle not in logged
    assert "failed reading" not in logged
    assert all(record.exc_info is None for record in caplog.records)


class ExplodingStatus(InMemoryLibrary):
    """Every status change after the start fails."""

    started = False

    def set_recording_status(self, recording_id: str, status: Any, **kwargs: Any) -> Any:
        if self.started:
            raise RuntimeError(LEAKY_TEXT)
        self.started = True
        return super().set_recording_status(recording_id, status, **kwargs)


def test_a_run_never_raises_even_when_the_reset_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig(ExplodingStatus.from_seed())
    with caplog.at_level(logging.WARNING, logger="askfootage.indexing"):
        _start_and_run(rig)
    assert rig.status(WAITING) == "preparing"
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "could not be set back to waiting" in logged
    assert FAKE_KEY not in logged


# --- The pipeline's own rules ---------------------------------------------------------------


@pytest.mark.parametrize(
    "nouns",
    [(), ("person", "person"), ("person", " "), ("person", "x" * 41), (" box",)],
)
def test_a_pipeline_refuses_bad_nouns(rig: Rig, nouns: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        IndexingPipeline(
            perception=rig.perception,
            preparer=rig.preparer,
            layout=rig.layout,
            tracks=rig.tracks,
            nouns=nouns,
            source_for=lambda recording: None,
        )


def test_a_pipeline_keeps_its_nouns_as_a_tuple(rig: Rig) -> None:
    pipeline = IndexingPipeline(
        perception=rig.perception,
        preparer=rig.preparer,
        layout=rig.layout,
        tracks=rig.tracks,
        nouns=["person"],  # type: ignore[arg-type]
        source_for=lambda recording: None,
    )
    assert pipeline.nouns == ("person",)


# --- Adding a concept -----------------------------------------------------------------------


def test_a_concept_is_found_and_saved_for_a_ready_recording(rig: Rig) -> None:
    rig.perception.tracks["forklift"] = [make_track(3, "forklift", [4, 5, 6])]
    saved = concepts.add_concept(rig.library, rig.pipeline, READY, "  forklift ")
    assert saved == 1
    assert rig.perception.calls == [(rig.layout.prepared_path(READY), "forklift")]
    assert [track.track_id for track in rig.tracks.tracks_for(READY, "forklift")] == [3]
    assert rig.store.status_log == []
    assert rig.preparer.calls == []


def test_a_concept_with_nothing_found_saves_none(rig: Rig) -> None:
    assert concepts.add_concept(rig.library, rig.pipeline, READY, "ladder") == 0
    assert rig.tracks.calls == [(READY, "ladder")]


@pytest.mark.parametrize("recording_id", [WAITING, PREPARING, INDEXING])
def test_a_concept_is_refused_unless_the_recording_is_ready(rig: Rig, recording_id: str) -> None:
    with pytest.raises(RecordingNotReadyError):
        concepts.add_concept(rig.library, rig.pipeline, recording_id, "forklift")
    assert rig.perception.calls == [] and rig.tracks.calls == []


def test_a_concept_without_a_pipeline_is_not_configured(store: InMemoryLibrary) -> None:
    with pytest.raises(IndexingNotConfiguredError):
        concepts.add_concept(Library.from_store(store), None, READY, "forklift")


def test_a_concept_on_an_unknown_recording_is_not_found(rig: Rig) -> None:
    with pytest.raises(NotFoundError):
        concepts.add_concept(rig.library, rig.pipeline, "rec-nope", "forklift")


@pytest.mark.parametrize("noun", ["", "   ", "x" * 41])
def test_a_bad_concept_noun_is_refused_by_name(rig: Rig, noun: str) -> None:
    with pytest.raises(InvalidInputError) as raised:
        concepts.add_concept(rig.library, rig.pipeline, READY, noun)
    assert raised.value.field == "noun"
    assert "x" * 41 not in raised.value.message
    assert rig.perception.calls == []


@pytest.mark.parametrize(
    "error", [PerceptionError(LEAKY_TEXT), RuntimeError(LEAKY_TEXT), ValueError(LEAKY_TEXT)]
)
def test_a_concept_whose_perception_fails_saves_nothing_and_says_so_safely(
    store: InMemoryLibrary, error: Exception
) -> None:
    rig = Rig(store, perception=FakePerception(error=error))
    with pytest.raises(IndexingFailedError) as raised:
        concepts.add_concept(rig.library, rig.pipeline, READY, "forklift")
    _assert_safe_note(raised.value.message)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert rig.tracks.calls == []


def test_a_concept_on_a_build_whose_perception_is_not_configured_says_so(
    store: InMemoryLibrary,
) -> None:
    rig = Rig(store, perception=FakePerception(error=PerceptionNotConfiguredError()))
    with pytest.raises(IndexingNotConfiguredError):
        concepts.add_concept(rig.library, rig.pipeline, READY, "forklift")
    assert rig.tracks.calls == []


def test_a_concept_whose_tracks_have_the_wrong_label_saves_nothing(
    store: InMemoryLibrary,
) -> None:
    rig = Rig(store, perception=FakePerception({"forklift": [make_track(0, "person", [1])]}))
    with pytest.raises(IndexingFailedError):
        concepts.add_concept(rig.library, rig.pipeline, READY, "forklift")
    assert rig.tracks.saved == {}


# --- Layering -------------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["ingest_video.py", "add_concept.py"])
def test_the_indexing_use_cases_import_no_adapter_and_no_relation_rules(module: str) -> None:
    source = REPO_ROOT / "askfootage" / "application" / module
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in imported:
        assert not name.startswith("askfootage.adapters"), name
        assert not name.startswith("askfootage.interfaces"), name
        assert name not in ("askfootage.domain.relations", "askfootage.domain.vocabulary"), name
