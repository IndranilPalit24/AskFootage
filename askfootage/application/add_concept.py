"""Adding a concept: find one more object noun in a recording that is already indexed.

It runs perception for the new noun on the prepared working copy and saves the tracks,
replacing any saved for that noun before. The recording's status does not change.
POST /api/concepts reaches it through application/concepts.py.
"""

from __future__ import annotations

import logging

from askfootage.application.errors import (
    IndexingFailedError,
    IndexingNotConfiguredError,
    InvalidInputError,
    NoRecordedResultError,
    NotFoundError,
    RecordingNotReadyError,
)
from askfootage.application.ingest_video import (
    BUDGET_REFUSED_PREFIX,
    FIND_FAILED_NOTE,
    RECORDING_NOT_FOUND,
    SAVE_FAILED_NOTE,
    IndexingPipeline,
    IngestBudgetError,
    IngestResult,
    IngestServices,
    clean_concepts,
    noun_problem,
    prepared_path_for_reading,
    recorded_info,
    require_configured,
    run_concepts,
    video_folder,
)
from askfootage.application.library import Library
from askfootage.ports.budget import BudgetError
from askfootage.ports.library_store import MissingReferenceError
from askfootage.ports.perception import Perception, PerceptionNotConfiguredError
from askfootage.ports.track_store import TrackStore
from askfootage.ports.video_store import VideoFileLayout

logger = logging.getLogger("askfootage.indexing")


def add_concept(
    library: Library, pipeline: IndexingPipeline | None, recording_id: str, noun: str
) -> int:
    """Find `noun` (trimmed) in a ready recording and save its tracks; returns how many.

    Raises IndexingNotConfiguredError without a pipeline (or when its perception says it is
    not configured), InvalidInputError (field noun)
    for a blank or over-long noun, NotFoundError for an unknown recording,
    RecordingNotReadyError unless it is ready, and IndexingFailedError with a fixed message
    when finding or saving the tracks fails (nothing is saved then).
    """
    if pipeline is None:
        raise IndexingNotConfiguredError()
    return find_concept(
        library, pipeline.perception, pipeline.layout, pipeline.tracks, recording_id, noun
    )


def find_concept(
    library: Library,
    perception: Perception,
    layout: VideoFileLayout,
    tracks: TrackStore,
    recording_id: str,
    noun: str,
) -> int:
    """The work of add_concept() with its parts given one by one; same rules and errors.

    The caller may pass a budgeted perception: a refusal by its budget is raised as
    IngestBudgetError (nothing was sent, nothing saved), and a NoRecordedResultError from a
    replaying perception passes through unchanged. Both carry fixed messages.
    """
    concept = noun.strip()
    problem = noun_problem(concept)
    if problem is not None:
        raise InvalidInputError("noun", problem)
    recording = library.recordings.get_recording(recording_id)
    if recording is None:
        raise NotFoundError(RECORDING_NOT_FOUND)
    if recording.status != "ready":
        raise RecordingNotReadyError()
    video = layout.prepared_path(recording_id)
    try:
        found = list(perception.detect_and_track(video, concept))
    except PerceptionNotConfiguredError:
        raise IndexingNotConfiguredError() from None
    except NoRecordedResultError:
        raise
    except BudgetError as error:
        raise IngestBudgetError(f"{BUDGET_REFUSED_PREFIX}{error}") from None
    except Exception as error:  # perception is outside code; any failure is one
        logger.error("Adding a concept to %s failed (%s)", recording_id, type(error).__name__)
        raise IndexingFailedError(FIND_FAILED_NOTE) from None
    try:
        tracks.save_tracks(recording_id, concept, found)
    except MissingReferenceError:
        raise NotFoundError(RECORDING_NOT_FOUND) from None
    except ValueError as error:
        logger.error("Saving a concept for %s failed (%s)", recording_id, type(error).__name__)
        raise IndexingFailedError(SAVE_FAILED_NOTE) from None
    return len(found)


def add_video_concept(
    services: IngestServices, video_id: str, concept: str, *, force: bool = False
) -> IngestResult:
    """Add one concept to a video that ingest_video() already prepared.

    Only the new concept goes to perception (and the budget); the video is not prepared
    again and other concepts' tracks are untouched. A concept already stored is skipped
    unless force. Raises InvalidInputError for a bad concept or id, NotFoundError when the
    video was never ingested, and the same typed errors as ingest_video().
    """
    (wanted,) = clean_concepts([concept])
    video_folder(services, video_id, create=False)
    require_configured(services.perception)
    prepared = prepared_path_for_reading(services, video_id)
    if not prepared.exists():
        raise NotFoundError("That video has not been ingested yet.")
    recorded = recorded_info(services.tracks, video_id)
    return run_concepts(
        services,
        video_id,
        prepared,
        [wanted],
        force,
        frame_count=recorded[0] if recorded else None,
    )
