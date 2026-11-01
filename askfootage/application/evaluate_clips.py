"""Compare hand-made clip labels (seconds) with what the relation layer finds in stored tracks.

Labels are written in seconds of the clip (see labels/README.md); the relation rules work in
frames of the 5 fps copy. This module runs the same rules search uses (tracks stitched, then
carrying, then merged) and turns the frames it finds into seconds, so each labelled event
can be shown next to what was found:

- carrying: the intervals relations.carrying finds for the person and the labelled object.
- in_frame: the stretches during which the person was tracked.
- leaves_room: there is no rule for it and no zone to define it by, so it is reported as
  not evaluable, with the time the object was last seen for context. Nothing is invented.

An event labelled "unconfirmed" is shown but never scored. A confirmed event is a match when
the found time overlaps the labelled time with IoU of at least MATCH_IOU. Found intervals are
[first frame start, last frame end) in seconds, so one frame at 5 fps is 0.2 s long.
Standard library, domain and ports only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from askfootage.application.clip_labels import ClipEvent, ClipLabels
from askfootage.domain import relations
from askfootage.domain.stitching import merge_intervals, stitch_tracks
from askfootage.domain.timebase import DEFAULT_ANALYSIS_FPS, Timebase
from askfootage.domain.tracks import Track
from askfootage.ports.track_store import TrackStore

MATCH_IOU = 0.5
"""Least overlap (intersection over union, in seconds) for a found time to match a label."""
OBJECT_LABELS = {"box": "cardboard box"}
"""Label-file object name -> the noun its tracks are stored under."""
PERSON = "person"

Span = tuple[float, float]


@dataclass(frozen=True, slots=True)
class EventResult:
    """One labelled event next to what was found."""

    event: ClipEvent
    found: tuple[Span, ...]
    verdict: str
    """match, miss, not scored (unconfirmed) or not evaluable (no rule)."""
    iou: float | None
    note: str = ""


@dataclass(frozen=True, slots=True)
class ClipEvaluation:
    clip: str
    rows: tuple[EventResult, ...]

    @property
    def scored(self) -> int:
        return sum(1 for row in self.rows if row.verdict in ("match", "miss"))

    @property
    def matched(self) -> int:
        return sum(1 for row in self.rows if row.verdict == "match")


def _iou(a: Span, b: Span) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    if union <= 0:  # two instants: equal or not
        return 1.0 if a == b else 0.0
    return inter / union


def _spans(tracks: list[Track], timebase: Timebase) -> tuple[Span, ...]:
    """Merged stretches during which any of the tracks was seen, in seconds."""
    frames = sorted({f for t in tracks for f in t.frames})
    runs: list[list[int]] = []
    for frame in frames:
        if runs and frame - runs[-1][1] <= relations.DEFAULT_THRESHOLDS.gap_tolerance_frames + 1:
            runs[-1][1] = frame
        else:
            runs.append([frame, frame])
    return tuple((timebase.frame_to_seconds(a), timebase.frame_to_seconds(b + 1)) for a, b in runs)


def evaluate_clip(
    labels: ClipLabels,
    tracks: TrackStore,
    video_id: str,
    thresholds: relations.Thresholds = relations.DEFAULT_THRESHOLDS,
) -> ClipEvaluation:
    """Each labelled event of the clip next to what the relation layer finds in its tracks."""
    timebase = Timebase(DEFAULT_ANALYSIS_FPS)

    cache: dict[str, list[Track]] = {}

    def stitched(label: str) -> list[Track]:
        if label not in cache:
            cache[label] = stitch_tracks(tracks.tracks_for(video_id, label))
        return cache[label]

    people = stitched(PERSON)
    rows = [_row(event, people, stitched, thresholds, timebase) for event in labels.events]
    return ClipEvaluation(labels.clip, tuple(rows))


def _row(
    event: ClipEvent,
    people: list[Track],
    stitched: Callable[[str], list[Track]],
    thresholds: relations.Thresholds,
    timebase: Timebase,
) -> EventResult:
    expected: Span = (event.start_s, event.end_s)
    objects = stitched(OBJECT_LABELS.get(event.object, event.object))
    note = ""
    if event.type == "carrying":
        found_intervals = merge_intervals(
            relations.carrying(people, objects, thresholds), thresholds.gap_tolerance_frames
        )
        found = tuple(
            (
                timebase.frame_to_seconds(i.start_frame),
                timebase.frame_to_seconds(i.end_frame + 1),
            )
            for i in found_intervals
        )
    elif event.type == "in_frame":
        found = _spans(stitched(event.object) if event.object != PERSON else people, timebase)
    else:  # leaves_room
        found = ()
        seen = [t.last_frame for t in objects]
        last = (
            f"; the {event.object} was last seen at {timebase.frame_to_seconds(max(seen)):.1f} s"
            if seen
            else ""
        )
        note = f"no rule for leaving the room and no zone to define it by{last}"
        return EventResult(event, found, "not evaluable", None, note)
    iou = max((_iou(expected, span) for span in found), default=None)
    if event.status != "confirmed":
        return EventResult(event, found, "not scored", iou, "labelled unconfirmed")
    verdict = "match" if iou is not None and iou >= MATCH_IOU else "miss"
    return EventResult(event, found, verdict, iou, note)
