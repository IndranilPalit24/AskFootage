"""The boxes of a recording's stored object tracks, for the player to draw over the video.

Reads through the TrackStore port only. Hands are left out. Short, isolated runs of an
object (not a person) are detector noise and are dropped here, in what is shown; the stored
tracks, their labels and the search thresholds are not changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from askfootage.application.errors import ApplicationError, NotFoundError
from askfootage.application.library import Library
from askfootage.application.search_relations import FrameSizeSource
from askfootage.domain.timebase import DEFAULT_ANALYSIS_FPS
from askfootage.domain.tracks import Track
from askfootage.ports.track_store import TrackLabelIndex, TrackStore

HIDDEN_LABELS = frozenset({"hand"})
"""Labels never shown as boxes."""
PERSON_LABEL = "person"
MIN_BOX_RUN_SECONDS = 1.0
"""An object must be seen for at least this long in one run to be drawn. At the analysis
rate of 5 fps a run must span at least 5 frames."""
MAX_RUN_FRAME_STEP = 2
"""Two detections at most this many frames apart (one missed frame between) are one run."""
DEMO_FRAME_SIZE = (1920.0, 1080.0)
"""Reported only when there are no tracks, so no box depends on it."""


@dataclass(frozen=True, slots=True)
class BoxPointView:
    """One box on one frame, in pixels."""

    frame: int
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True, slots=True)
class BoxTrackView:
    """One track to draw."""

    track_id: int
    label: str
    role: Literal["person", "object"]
    points: tuple[BoxPointView, ...]


@dataclass(frozen=True, slots=True)
class RecordingBoxesView:
    """Every drawable track of one recording."""

    recording_id: str
    frame_width: float
    frame_height: float
    fps: float
    tracks: tuple[BoxTrackView, ...]


def long_runs(frames: list[int], fps: float) -> set[int]:
    """The frames (sorted, distinct) that belong to a run of at least MIN_BOX_RUN_SECONDS."""
    needed = MIN_BOX_RUN_SECONDS * fps
    kept: set[int] = set()
    run: list[int] = []
    for frame in [*frames, None]:
        if frame is not None and (not run or frame - run[-1] <= MAX_RUN_FRAME_STEP):
            run.append(frame)
            continue
        if run and run[-1] - run[0] + 1 >= needed:
            kept.update(run)
        run = [] if frame is None else [frame]
    return kept


def _view_of(track: Track, fps: float) -> BoxTrackView | None:
    is_person = track.label == PERSON_LABEL
    points = sorted(track.points, key=lambda point: point.frame)
    if not is_person:
        keep = long_runs([point.frame for point in points], fps)
        points = [point for point in points if point.frame in keep]
    if not points:
        return None
    return BoxTrackView(
        track_id=track.track_id,
        label=track.label,
        role="person" if is_person else "object",
        points=tuple(BoxPointView(p.frame, p.box.x1, p.box.y1, p.box.x2, p.box.y2) for p in points),
    )


def get_recording_boxes(
    library: Library,
    tracks: TrackStore | None,
    frame_size: FrameSizeSource | None,
    recording_id: str,
) -> RecordingBoxesView:
    """The boxes of a known recording; NotFoundError when the recording is unknown.

    A recording without stored tracks (or an app without a track store) gives no tracks.
    ApplicationError (a 500) when tracks exist but their frame size is not known.
    """
    if library.recordings.get_recording(recording_id) is None:
        raise NotFoundError("Recording not found.")
    fps = float(DEFAULT_ANALYSIS_FPS)
    found: list[BoxTrackView] = []
    labels_of = getattr(tracks, "labels_for", None)
    if tracks is not None and callable(labels_of):
        index: TrackLabelIndex = tracks  # type: ignore[assignment]
        for label in index.labels_for(recording_id):
            if label in HIDDEN_LABELS:
                continue
            for track in tracks.tracks_for(recording_id, label):
                view = _view_of(track, fps)
                if view is not None:
                    found.append(view)
    if not found:
        width, height = DEMO_FRAME_SIZE
        return RecordingBoxesView(recording_id, width, height, fps, ())
    size = frame_size(recording_id) if frame_size is not None else None
    if size is None or size[0] <= 0 or size[1] <= 0:
        raise ApplicationError("The frame size of this recording is not recorded.")
    found.sort(key=lambda view: (view.label != PERSON_LABEL, view.label, view.track_id))
    return RecordingBoxesView(recording_id, float(size[0]), float(size[1]), fps, tuple(found))
