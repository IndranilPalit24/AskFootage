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

import hashlib
import logging
import os
import shutil
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from askfootage.application.budgeted_perception import BudgetedPerception
from askfootage.application.errors import (
    ApplicationError,
    IndexingFailedError,
    IndexingNotConfiguredError,
    InvalidInputError,
    NotFoundError,
    RecordingNotWaitingError,
)
from askfootage.application.library import Library
from askfootage.domain.stitching import DEFAULT_STITCH, StitchParams, stitch_tracks
from askfootage.domain.tracks import LABEL_MAX, Track
from askfootage.ports.budget import Budget, BudgetError
from askfootage.ports.library_store import Recording, RecordingStatus
from askfootage.ports.perception import (
    NOT_CONFIGURED_MESSAGE,
    Perception,
    PerceptionNotConfiguredError,
)
from askfootage.ports.track_store import TrackDataError, TrackStore
from askfootage.ports.video_store import (
    PreparedVideo,
    VideoFileLayout,
    VideoPreparer,
)

logger = logging.getLogger("askfootage.indexing")

RECORDING_NOT_FOUND = "Recording not found."
UNKNOWN_FINGERPRINT = "unknown"

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


# --- ingesting a video by id, without the recordings library ------------------------------

BUDGET_REFUSED_PREFIX = "Stopped before the spending cap was passed: "
SOURCE_CHANGED_NOTE = (
    "The source video changed since it was ingested. Run again with --force to redo it."
)
FALLBACK_FRAMES = 3000
"""Frames assumed when pricing a call for a video whose frame count was never recorded
(about 10 minutes at 5 fps): deliberately high, so the cap errs on the safe side."""


class VideoPrepareFailedError(ApplicationError):
    """The source video could not be turned into the working copy."""


class IngestBudgetError(ApplicationError):
    """The budget refused a perception call. The message states amounts only."""


class SourceChangedError(ApplicationError):
    """The source file differs from the one the working copy was made from."""


@dataclass(frozen=True, slots=True)
class IngestServices:
    """What ingest_video() and add_video_concept() work with: the ports, no adapters.

    budget is optional; when given, every perception call reserves its cost first (see
    BudgetedPerception). The cost of a call is cost_per_concept, unless estimate_cost is
    given: then it is estimate_cost(frame count of the prepared video), never less than
    cost_per_concept, so an override can raise the estimate but not lower it. stitch tunes
    how track fragments are joined.

    The track store may also offer (JsonTrackStore does): concept_done(video, concept),
    save_frame_size(video, w, h), save_prepared_info(video, frame_count=, source_fingerprint=)
    and prepared_info(video). They are used when present.
    """

    perception: Perception
    preparer: VideoPreparer
    layout: VideoFileLayout
    tracks: TrackStore
    budget: Budget | None = None
    cost_per_concept: Decimal = Decimal(0)
    stitch: StitchParams = DEFAULT_STITCH
    estimate_cost: Callable[[int], Decimal] | None = None


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What one ingest did: tracks stored per concept it ran, the concepts it skipped
    because they were already searched for."""

    video_id: str
    track_counts: dict[str, int]
    skipped: tuple[str, ...]


def normalize_concept(raw: str) -> str:
    """Lower-cased (casefolded) with runs of whitespace made single spaces."""
    return " ".join(raw.casefold().split())


def clean_concepts(concepts: Sequence[str]) -> list[str]:
    """Normalised, de-duplicated (order kept) concepts; InvalidInputError for none or a bad one."""
    cleaned: list[str] = []
    for raw in concepts:
        concept = normalize_concept(raw)
        problem = noun_problem(concept)
        if problem is not None:
            raise InvalidInputError("concept", problem)
        if concept not in cleaned:
            cleaned.append(concept)
    if not cleaned:
        raise InvalidInputError("concepts", "give at least one concept")
    return cleaned


def video_folder(services: IngestServices, video_id: str, *, create: bool = True) -> Path:
    """The video's folder; InvalidInputError (field video_id) for an unsafe id.

    With create=False the folder is only checked, never made (read paths).
    """
    try:
        peek = getattr(services.layout, "peek_dir", None)
        if not create and peek is not None:
            return peek(video_id)
        return services.layout.video_dir(video_id)
    except ValueError:
        raise InvalidInputError("video_id", "must be 1 to 64 letters, digits, - or _") from None


def prepared_path_for_reading(services: IngestServices, video_id: str) -> Path:
    """Where the working copy is or would be, creating nothing."""
    peek = getattr(services.layout, "peek_prepared", None)
    return peek(video_id) if peek is not None else services.layout.prepared_path(video_id)


def _concept_done(tracks: TrackStore, video_id: str, concept: str) -> bool:
    """True when the concept was already searched for: the store's ran-empty marker if it
    has one, else any stored tracks. An unreadable store counts as not done."""
    try:
        marker = getattr(tracks, "concept_done", None)
        if marker is not None:
            return bool(marker(video_id, concept))
        return bool(tracks.tracks_for(video_id, concept))
    except TrackDataError:
        return False


def recorded_info(tracks: TrackStore, video_id: str) -> tuple[int, str] | None:
    """(frame count, source fingerprint) recorded at preparing time, if the store keeps it."""
    getter = getattr(tracks, "prepared_info", None)
    if getter is None:
        return None
    try:
        return getter(video_id)
    except TrackDataError:
        return None


def _source_fingerprint(source: Path) -> str | None:
    """A short hash of the source's size and modification time; None when it cannot be read."""
    try:
        stat = Path(source).stat()
    except OSError:
        return None
    return hashlib.sha256(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii")).hexdigest()[:32]


def _call_cost(services: IngestServices, frame_count: int | None) -> Decimal:
    if services.estimate_cost is None:
        return services.cost_per_concept
    frames = FALLBACK_FRAMES if frame_count is None else frame_count
    return max(services.estimate_cost(frames), services.cost_per_concept)


def run_concepts(
    services: IngestServices,
    video_id: str,
    video: Path,
    concepts: Sequence[str],
    force: bool,
    *,
    frame_count: int | None = None,
) -> IngestResult:
    """Perceive, stitch and store each concept not stored yet (all of them when force).

    A concept counts as stored once it was searched for, even when it matched nothing (the
    store keeps a ran-empty marker), so an empty result is not paid for twice. Concepts are
    saved one by one: when one fails, those before it stay saved and a re-run continues
    from it. `frame_count` prices each call (see IngestServices).
    """
    perception: Perception = services.perception
    if services.budget is not None:
        perception = BudgetedPerception(
            perception, services.budget, _call_cost(services, frame_count)
        )
    counts: dict[str, int] = {}
    skipped: list[str] = []
    for concept in concepts:
        if not force and _concept_done(services.tracks, video_id, concept):
            skipped.append(concept)
            continue
        try:
            found = perception.detect_and_track(video, concept)
        except PerceptionNotConfiguredError:
            raise IndexingNotConfiguredError() from None
        except BudgetError as error:
            raise IngestBudgetError(f"{BUDGET_REFUSED_PREFIX}{error}") from None
        except Exception as error:  # perception is outside code; any failure is one
            logger.error("Perceiving %s failed (%s)", video_id, type(error).__name__)
            raise IndexingFailedError(FIND_FAILED_NOTE) from None
        stitched = stitch_tracks(found, services.stitch)
        try:
            services.tracks.save_tracks(video_id, concept, stitched)
        except Exception as error:
            logger.error("Saving %s failed (%s)", video_id, type(error).__name__)
            raise IndexingFailedError(SAVE_FAILED_NOTE) from None
        counts[concept] = len(stitched)
    return IngestResult(video_id, counts, tuple(skipped))


def require_configured(perception: Perception) -> None:
    """IndexingNotConfiguredError when the perception says it is not configured
    (configured = False), so nothing slow runs first."""
    if getattr(perception, "configured", True) is False:
        raise IndexingNotConfiguredError()


def _prepare_atomically(
    services: IngestServices, source: Path, folder: Path, video_id: str
) -> PreparedVideo:
    """Run the preparer into a scratch folder, then move the copy into place in one rename,
    so an interrupted run never leaves a half-written prepared.mp4 behind."""
    scratch = Path(tempfile.mkdtemp(dir=folder, prefix=".prepare-"))
    try:
        prepared = services.preparer.prepare(Path(source), scratch)
        final = folder / services.layout.prepared_path(video_id).name
        os.replace(prepared.path, final)
        return PreparedVideo(
            final,
            prepared.fps,
            prepared.duration_seconds,
            prepared.frame_count,
            prepared.width,
            prepared.height,
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _record_prepared(
    services: IngestServices, video_id: str, prepared: PreparedVideo, fingerprint: str | None
) -> None:
    """Remember the copy's frame size, frame count and source fingerprint, if the store can."""
    tracks = services.tracks
    save_size = getattr(tracks, "save_frame_size", None)
    save_info = getattr(tracks, "save_prepared_info", None)
    try:
        if save_size is not None and prepared.width is not None and prepared.height is not None:
            save_size(video_id, prepared.width, prepared.height)
        if save_info is not None:
            save_info(
                video_id,
                frame_count=prepared.frame_count,
                source_fingerprint=fingerprint or UNKNOWN_FINGERPRINT,
            )
    except Exception as error:
        logger.error("Saving %s failed (%s)", video_id, type(error).__name__)
        raise IndexingFailedError(SAVE_FAILED_NOTE) from None


def ingest_video(
    services: IngestServices,
    video_id: str,
    source: Path,
    concepts: Sequence[str],
    *,
    force: bool = False,
) -> IngestResult:
    """Prepare `source` once, find each concept's tracks, stitch them and store them.

    Concepts are normalised (case-folded); the vocabulary is open here, so one outside it is
    stored like any other (the command line warns about it). Idempotent: concepts already
    searched for video_id are skipped (no call, no spend) and an existing working copy is
    reused, unless force. If the source file changed since the working copy was made (size or
    modification time), that is an error without force. Perception that is not configured
    is reported before any preparing. Raises InvalidInputError (bad concept or video id),
    SourceChangedError, VideoPrepareFailedError, IndexingNotConfiguredError,
    IngestBudgetError (cap reached; earlier concepts stay saved) or IndexingFailedError.
    All messages are fixed phrases or amounts: never a path, a key or a cause's text.
    """
    wanted = clean_concepts(concepts)
    folder = video_folder(services, video_id)
    require_configured(services.perception)
    prepared_file = prepared_path_for_reading(services, video_id)
    fingerprint = _source_fingerprint(source)
    recorded = recorded_info(services.tracks, video_id)
    exists = prepared_file.exists()
    changed = (
        recorded is not None
        and fingerprint is not None
        and recorded[1] not in (fingerprint, UNKNOWN_FINGERPRINT)
    )
    if exists and changed and not force:
        raise SourceChangedError(SOURCE_CHANGED_NOTE)
    pending = force or any(not _concept_done(services.tracks, video_id, c) for c in wanted)
    frame_count = recorded[0] if recorded else None
    if pending and (force or not exists):
        try:
            prepared = _prepare_atomically(services, source, folder, video_id)
        except Exception as error:
            logger.error("Preparing %s failed (%s)", video_id, type(error).__name__)
            raise VideoPrepareFailedError(PREPARE_FAILED_NOTE) from None
        _record_prepared(services, video_id, prepared, fingerprint)
        frame_count = prepared.frame_count
    return run_concepts(services, video_id, prepared_file, wanted, force, frame_count=frame_count)
