"""Stitching: join track fragments into one track, and adjacent relation intervals into one.

Perception often loses an object for a moment and returns it as a new track. stitch_tracks
joins such fragments when they share a label, follow each other closely in time and pick up
where the last left off in space. merge_intervals joins intervals of the same relation and
tracks that touch or sit within a small gap. Frames only; output is deterministic whatever
the input order. Pure functions, standard library only.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from askfootage.domain.intervals import Interval, IntervalEvidence
from askfootage.domain.tracks import Track


@dataclass(frozen=True, slots=True)
class StitchParams:
    """When two fragments are one track.

    max_gap_frames: most frames missing between one fragment's last frame and the next's
        first. 15 frames is 3 s at 5 fps.
    max_center_shift: farthest the box centre may jump, as a fraction of the earlier box's
        larger side, per frame of elapsed time (gap + 1). 0.25 allows ordinary walking.
    max_shift_boxes: absolute cap on the same jump, in sizes of the earlier box's larger
        side, however long the gap: without it a long gap would let a track join anything
        across the frame. 2.0 means at most two box sizes.
    """

    max_gap_frames: int = 15
    max_center_shift: float = 0.25
    max_shift_boxes: float = 2.0

    def __post_init__(self) -> None:
        if isinstance(self.max_gap_frames, bool) or not isinstance(self.max_gap_frames, int):
            raise TypeError("max_gap_frames must be an int")
        if self.max_gap_frames < 0:
            raise ValueError("max_gap_frames must be at least 0")
        if not math.isfinite(self.max_center_shift) or self.max_center_shift < 0:
            raise ValueError("max_center_shift must be finite and at least 0")
        if not math.isfinite(self.max_shift_boxes) or self.max_shift_boxes < 0:
            raise ValueError("max_shift_boxes must be finite and at least 0")


DEFAULT_STITCH = StitchParams()


def _shift_allowed(chain: Track, fragment: Track, params: StitchParams) -> float | None:
    """Distance between the chain's last and the fragment's first centre if it is within
    reach, else None."""
    last = chain.points[-1].box
    first = fragment.points[0].box
    elapsed = fragment.first_frame - chain.last_frame
    (x0, y0), (x1, y1) = last.center, first.center
    distance = math.hypot(x1 - x0, y1 - y0)
    size = max(last.width, last.height)
    reach = min(params.max_center_shift * size * elapsed, params.max_shift_boxes * size)
    return distance if distance <= reach else None


def stitch_tracks(tracks: Iterable[Track], params: StitchParams = DEFAULT_STITCH) -> list[Track]:
    """Tracks with fragments of the same object joined.

    A fragment joins an earlier one when the labels match, it starts after the earlier one
    ends (never overlapping), the gap is at most max_gap_frames and the centre jump is
    within max_center_shift. Each fragment joins the nearest eligible earlier one, and
    each earlier one takes at most one successor, so chains form but nothing splits. The
    joined track keeps the id of its earliest fragment. Result is sorted by first frame,
    then track id.
    """
    ordered = sorted(tracks, key=lambda t: (t.first_frame, t.track_id, t.label))
    chains: list[Track] = []
    for fragment in ordered:
        best_index: int | None = None
        best_distance = math.inf
        for index, chain in enumerate(chains):
            if chain.label != fragment.label or chain.last_frame >= fragment.first_frame:
                continue
            if fragment.first_frame - chain.last_frame - 1 > params.max_gap_frames:
                continue
            distance = _shift_allowed(chain, fragment, params)
            if distance is not None and distance < best_distance:
                best_index, best_distance = index, distance
        if best_index is None:
            chains.append(fragment)
        else:
            head = chains[best_index]
            chains[best_index] = Track(head.track_id, head.label, head.points + fragment.points)
    return sorted(chains, key=lambda t: (t.first_frame, t.track_id, t.label))


# --- intervals ---------------------------------------------------------------------------

_SUMMED_PREFIX = "frames_"
_FIRST_MEASURES = frozenset({"started_inside"})
_LAST_MEASURES = frozenset({"ended_inside"})


def _combine(parts: list[Interval]) -> Interval:
    start = min(p.start_frame for p in parts)
    end = max(p.end_frame for p in parts)
    first, last = parts[0], parts[-1]
    names: list[str] = []
    for part in parts:
        for name, _ in part.evidence.measures:
            if name not in names:
                names.append(name)
    measures: list[tuple[str, float]] = []
    for name in names:
        values = [(p, dict(p.evidence.measures).get(name)) for p in parts]
        present = [(p, v) for p, v in values if v is not None]
        if name.startswith(_SUMMED_PREFIX):
            value = sum(v for _, v in present)
        elif name in _FIRST_MEASURES:
            value = dict(first.evidence.measures).get(name, present[0][1])
        elif name in _LAST_MEASURES:
            value = dict(last.evidence.measures).get(name, present[-1][1])
        else:
            weight = sum(p.frame_count for p, _ in present)
            value = sum(p.frame_count * v for p, v in present) / weight
        measures.append((name, float(value)))
    evidence = IntervalEvidence(first.evidence.kind, first.evidence.track_ids, tuple(measures))
    return Interval(start, end, evidence)


def merge_intervals(intervals: Iterable[Interval], max_gap_frames: int = 0) -> list[Interval]:
    """Intervals of the same kind and tracks joined when they overlap, touch or are
    separated by at most `max_gap_frames` empty frames.

    Measures combine as follows: names starting "frames_" add up, "started_inside" comes
    from the earliest part and "ended_inside" from the latest, everything else is the mean
    weighted by each part's frame count. Result is sorted by start, end, then track ids.
    """
    if isinstance(max_gap_frames, bool) or not isinstance(max_gap_frames, int):
        raise TypeError("max_gap_frames must be an int")
    if max_gap_frames < 0:
        raise ValueError("max_gap_frames must be at least 0")
    groups: dict[tuple[str, tuple[int, ...]], list[Interval]] = {}
    for interval in intervals:
        key = (interval.evidence.kind, interval.evidence.track_ids)
        groups.setdefault(key, []).append(interval)
    merged: list[Interval] = []
    for group in groups.values():
        group.sort(key=lambda i: (i.start_frame, i.end_frame))
        run: list[Interval] = [group[0]]
        run_end = group[0].end_frame
        for interval in group[1:]:
            if interval.start_frame - run_end - 1 <= max_gap_frames:
                run.append(interval)
                run_end = max(run_end, interval.end_frame)
            else:
                merged.append(_combine(run) if len(run) > 1 else run[0])
                run, run_end = [interval], interval.end_frame
        merged.append(_combine(run) if len(run) > 1 else run[0])
    return sorted(
        merged,
        key=lambda i: (i.start_frame, i.end_frame, i.evidence.track_ids, i.evidence.kind),
    )
