"""Indexing a recording: waiting -> preparing -> indexing -> ready, or back to waiting.

Two steps, so the HTTP reply does not wait for the slow part:
- start_indexing() runs inside the request. It claims the recording with an atomic
  compare-and-set (waiting -> preparing), so two callers can never both start it.
- run_indexing() runs after the reply. It makes the working copy, finds every object
  named by the pipeline's nouns, saves their tracks and marks the recording ready. Any
  failure puts the recording back to waiting with a short, fixed status note, so it can
  be started again.

Everything this needs arrives through IndexingPipeline, typed with the ports; this module
imports no adapter. Clips are not made from relation intervals yet: an interval's
evidence names its tracks by id only (ids are unique per noun, not per video) and does not
say which zone an in_zone or dwell interval was in, so a clip's label, zone and evidence
text cannot be built from it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from askfootage.application.errors import (
    IndexingNotConfiguredError,
    NotFoundError,
    RecordingNotWaitingError,
)
from askfootage.application.library import Library
from askfootage.domain.tracks import LABEL_MAX, Track
from askfootage.ports.library_store import Recording, RecordingStatus
from askfootage.ports.perception import (
    NOT_CONFIGURED_MESSAGE,
    Perception,
    PerceptionNotConfiguredError,
)
from askfootage.ports.track_store import TrackStore
from askfootage.ports.video_store import VideoFileLayout, VideoPreparer

logger = logging.getLogger("askfootage.indexing")

RECORDING_NOT_FOUND = "Recording not found."

# Status notes. Each is a fixed phrase: never an exception's text, a path or a key.
FAILED_NOTE = "Indexing failed. Try again."
SOURCE_MISSING_NOTE = "The uploaded video file could not be found."
PREPARE_FAILED_NOTE = "The video could not be prepared for indexing."
FIND_FAILED_NOTE = "Finding objects in the video failed."
SAVE_FAILED_NOTE = "The objects found could not be saved."
FINISH_FAILED_NOTE = "Indexing could not be finished."
NOT_CONFIGURED_NOTE = f"{NOT_CONFIGURED_MESSAGE}."

SourceFinder = Callable[[Recording], Path | None]
"""The uploaded video of a recording, or None when there is no file for it."""

_NOUN_RULE = f"must be 1 to {LABEL_MAX} characters, not blank"


def noun_problem(noun: str) -> str | None:
    """What is wrong with an object noun (it must be trimmed, 1 to 40 characters), or None."""
    if not noun.strip() or noun != noun.strip() or len(noun) > LABEL_MAX:
        return _NOUN_RULE
    return None


@dataclass(frozen=True, slots=True)
class IndexingPipeline:
    """What indexing works with: one implementation of each port, and the nouns to find.

    nouns are the object nouns every recording is indexed for, such as "person" and
    "cardboard box": trimmed, 1 to 40 characters, no repeats, at least one. A build
    without perception has no pipeline at all (the API holds None and answers 503).
    """

    perception: Perception
    preparer: VideoPreparer
    layout: VideoFileLayout
    tracks: TrackStore
    nouns: Sequence[str]
    source_for: SourceFinder

    def __post_init__(self) -> None:
        nouns = tuple(self.nouns)
        if not nouns:
            raise ValueError("an indexing pipeline needs at least one noun")
        if len(set(nouns)) != len(nouns):
            raise ValueError("an indexing pipeline's nouns must not repeat")
        for noun in nouns:
            problem = noun_problem(noun)
            if problem is not None:
                raise ValueError(f"each noun {problem} and trimmed")
        object.__setattr__(self, "nouns", nouns)


@dataclass(frozen=True, slots=True)
class IndexingJob:
    """A claimed recording (status preparing) and the work still to do for it."""

    library: Library
    pipeline: IndexingPipeline
    recording: Recording

    def run(self) -> None:
        """Do the work: run_indexing() for this recording. Never raises."""
        run_indexing(self.library, self.pipeline, self.recording.id)


def start_indexing(
    library: Library, pipeline: IndexingPipeline | None, recording_id: str
) -> IndexingJob:
    """Claim a waiting recording for indexing; returns it (now preparing) with its job.

    Raises IndexingNotConfiguredError when there is no pipeline (before looking anything
    up or changing anything), NotFoundError for an unknown recording, and
    RecordingNotWaitingError when it is not waiting, including when another caller
    claimed it first. Any earlier status note is cleared. The caller then arranges for
    job.run() to be called, typically after replying.
    """
    if pipeline is None:
        raise IndexingNotConfiguredError()
    if library.recordings.get_recording(recording_id) is None:
        raise NotFoundError(RECORDING_NOT_FOUND)
    started = library.recordings.set_recording_status(recording_id, "preparing", expected="waiting")
    if started is not None:
        return IndexingJob(library=library, pipeline=pipeline, recording=started)
    if library.recordings.get_recording(recording_id) is None:
        raise NotFoundError(RECORDING_NOT_FOUND)
    raise RecordingNotWaitingError()


def run_indexing(library: Library, pipeline: IndexingPipeline, recording_id: str) -> None:
    """Index a recording that start_indexing() claimed. Never raises.

    preparing: make the working copy in layout.video_dir(id). indexing: find each noun's
    tracks in it, then save them (each noun's tracks replace any saved before). Then
    ready, with no note. Each status change is a compare-and-set from the status before
    it, so if the recording was deleted or changed by someone else meanwhile, the run
    stops and leaves it alone. On any failure the recording goes back to waiting with a
    fixed note for the stage that failed; the log gets the stage and the error's type,
    never its text.
    """
    stage: RecordingStatus = "preparing"
    note = FAILED_NOTE
    try:
        recording = library.recordings.get_recording(recording_id)
        if recording is None or recording.status != "preparing":
            logger.warning("Indexing %s skipped: it is not being prepared", recording_id)
            return
        note = SOURCE_MISSING_NOTE
        source = pipeline.source_for(recording)
        if source is None:
            raise _SourceMissingError()
        note = PREPARE_FAILED_NOTE
        prepared = pipeline.preparer.prepare(source, pipeline.layout.video_dir(recording_id))
        if not _advance(library, recording_id, "indexing", expected="preparing"):
            return
        stage = "indexing"
        note = FIND_FAILED_NOTE
        found: dict[str, list[Track]] = {
            noun: list(pipeline.perception.detect_and_track(prepared.path, noun))
            for noun in pipeline.nouns
        }
        note = SAVE_FAILED_NOTE
        for noun, tracks in found.items():
            pipeline.tracks.save_tracks(recording_id, noun, tracks)
        note = FINISH_FAILED_NOTE
        if not _advance(library, recording_id, "ready", expected="indexing"):
            return
    except Exception as error:  # every failure must end in waiting, not a crash
        if isinstance(error, PerceptionNotConfiguredError):
            note = NOT_CONFIGURED_NOTE
        logger.error("Indexing %s failed while %s (%s)", recording_id, stage, type(error).__name__)
        _back_to_waiting(library, recording_id, stage, note)
        return
    total = sum(len(tracks) for tracks in found.values())
    logger.info("Indexed %s: %d tracks for %d nouns", recording_id, total, len(found))


class _SourceMissingError(Exception):
    """The recording has no uploaded video to index."""


def _advance(
    library: Library, recording_id: str, status: RecordingStatus, *, expected: RecordingStatus
) -> bool:
    """Move expected -> status; False (and logged) when the recording is gone or changed."""
    changed = library.recordings.set_recording_status(recording_id, status, expected=expected)
    if changed is not None:
        return True
    logger.warning(
        "Indexing %s stopped: it was deleted or changed while %s", recording_id, expected
    )
    return False


def _back_to_waiting(
    library: Library, recording_id: str, stage: RecordingStatus, note: str
) -> None:
    """Put a failed recording back to waiting with its note, if it is still in `stage`."""
    try:
        reset = library.recordings.set_recording_status(
            recording_id, "waiting", expected=stage, note=note
        )
    except Exception as error:  # this runs after the reply; nobody to raise to
        logger.error(
            "Recording %s could not be set back to waiting (%s)",
            recording_id,
            type(error).__name__,
        )
        return
    if reset is None:
        logger.warning(
            "Recording %s could not be set back to waiting: it was deleted or changed",
            recording_id,
        )
