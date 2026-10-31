"""Relation rules: when an object was carried, when a track was in a zone, and dwell.

Each rule reads object tracks and returns Interval values (intervals.py) with the evidence
for why they matched. Rules work in frames only; convert to seconds at the edge with a
Timebase (see min_frames_for and Interval.seconds). Output is deterministic: intervals are
sorted by start frame, then end frame, then track ids, whatever order the tracks came in.

Zone polygons must be in the same pixel coordinates as the track boxes. Every number a rule
depends on is a named field of Thresholds. Pure functions, standard library only.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from askfootage.domain.geometry import containment, point_in_polygon, relative_offset
from askfootage.domain.intervals import Interval, IntervalEvidence
from askfootage.domain.models import BoundingBox, Point
from askfootage.domain.timebase import Timebase
from askfootage.domain.tracks import Track


def _check_number(name: str, value: float, *, low: float, high: float | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be a number; got {value!r}")
    if not math.isfinite(value) or value < low or (high is not None and value > high):
        upper = f" and at most {high}" if high is not None else ""
        raise ValueError(f"{name} must be finite, at least {low}{upper}; got {value!r}")


def _check_count(name: str, value: int, *, low: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int; got {value!r}")
    if value < low:
        raise ValueError(f"{name} must be at least {low}; got {value}")


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Every tunable number the relation rules use, with defaults for 5 fps footage.

    carry_near_margin: how far outside a person's box a carried object's centre may be,
        as a fraction of the person's width (left and right) and height (above and below).
        0.15 allows an arm's reach beyond a tight person box.
    carry_containment: least fraction of the object's area that must lie inside the
        person's box grown by carry_near_margin. 0.5 keeps an object that merely touches
        the person's outline from counting as held.
    min_carry_frames: fewest frames a carry may span; 10 frames is 2 s at 5 fps, long
        enough that two tracks drifting past each other do not count.
    min_moving_displacement: least movement per frame, as a fraction of the person's box
        height, for the person or the object to count as moving. 0.02 is about 3.5 cm a
        frame for a 1.75 m person (walking is roughly 0.15); it ignores box jitter and
        camera shake, and it is why a box at rest beside a standing person is not carried.
    carry_motion_tolerance: largest allowed difference between the object's and the
        person's displacement on one step, as a fraction of the person's displacement.
        0.5 accepts a box that swings in the hand but rejects one that moves at a
        different speed or in a different direction.
    carry_min_agreement: least fraction of a carry's steps on which person and object
        moved together. Steps inside a joined gap count against it, so 0.6 lets a carry
        survive brief stumbles but not a run that is mostly disagreement.
    gap_tolerance_frames: most frames a relation may pause, or a track may go undetected,
        and still be one interval. 3 frames is 0.6 s at 5 fps: enough for a missed
        detection or a stumble, short of a real exit and return.
    min_zone_frames: fewest frames a region traversal may span. 2 ignores a foot point
        that flickers across a zone edge for a single frame.
    """

    carry_near_margin: float = 0.15
    carry_containment: float = 0.5
    min_carry_frames: int = 10
    min_moving_displacement: float = 0.02
    carry_motion_tolerance: float = 0.5
    carry_min_agreement: float = 0.6
    gap_tolerance_frames: int = 3
    min_zone_frames: int = 2

    def __post_init__(self) -> None:
        _check_number("carry_near_margin", self.carry_near_margin, low=0.0)
        _check_number("carry_containment", self.carry_containment, low=0.0, high=1.0)
        _check_count("min_carry_frames", self.min_carry_frames, low=1)
        _check_number("min_moving_displacement", self.min_moving_displacement, low=0.0)
        if self.min_moving_displacement == 0:
            raise ValueError("min_moving_displacement must be above 0")
        _check_number("carry_motion_tolerance", self.carry_motion_tolerance, low=0.0)
        _check_number("carry_min_agreement", self.carry_min_agreement, low=0.0, high=1.0)
        if self.carry_min_agreement == 0:
            raise ValueError("carry_min_agreement must be above 0")
        _check_count("gap_tolerance_frames", self.gap_tolerance_frames, low=0)
        _check_count("min_zone_frames", self.min_zone_frames, low=1)


DEFAULT_THRESHOLDS = Thresholds()
"""The thresholds every rule uses unless given others."""


def min_frames_for(seconds: float, timebase: Timebase) -> int:
    """Fewest whole frames spanning at least `seconds`, and never fewer than one.

    Use it to turn a question's minimum time into dwell's min_frames.
    """
    return max(1, timebase.frame_count_for(seconds))


# --- shared helpers ----------------------------------------------------------------------


def _join(spans: Iterable[tuple[int, int]], gap_tolerance: int) -> list[tuple[int, int]]:
    """Join inclusive (start, end) spans, given in start order, when they overlap, touch or
    are separated by at most `gap_tolerance` frames."""
    joined: list[tuple[int, int]] = []
    for start, end in spans:
        if joined and start - joined[-1][1] - 1 <= gap_tolerance:
            joined[-1] = (joined[-1][0], max(joined[-1][1], end))
        else:
            joined.append((start, end))
    return joined


def _sorted(intervals: list[Interval]) -> list[Interval]:
    """Exact duplicates removed (the same track given twice), then sorted by start, end,
    track ids and measures, so the order never depends on the input order."""
    return sorted(
        set(intervals),
        key=lambda i: (i.start_frame, i.end_frame, i.evidence.track_ids, i.evidence.measures),
    )


def _checked_polygon(polygon: Sequence[Point]) -> tuple[Point, ...]:
    vertices = tuple((float(x), float(y)) for x, y in polygon)
    if len(vertices) < 3:
        raise ValueError(f"a zone polygon needs at least 3 vertices; got {len(vertices)}")
    if not all(math.isfinite(v) for vertex in vertices for v in vertex):
        raise ValueError("zone polygon coordinates must be finite")
    return vertices


# --- carrying ----------------------------------------------------------------------------


def _is_near(obj: BoundingBox, person: BoundingBox, thresholds: Thresholds) -> bool:
    """The object's centre is inside the person's box grown by the margin, and enough of the
    object lies inside that grown box."""
    margin_x = thresholds.carry_near_margin * person.width
    margin_y = thresholds.carry_near_margin * person.height
    x1, y1 = person.x1 - margin_x, person.y1 - margin_y
    x2, y2 = person.x2 + margin_x, person.y2 + margin_y
    cx, cy = obj.center
    if not (x1 <= cx <= x2 and y1 <= cy <= y2):
        return False
    return containment(obj, BoundingBox(x1, y1, x2, y2)) >= thresholds.carry_containment


def _moves_with(
    person_before: BoundingBox,
    person_after: BoundingBox,
    obj_before: BoundingBox,
    obj_after: BoundingBox,
    frames: int,
    thresholds: Thresholds,
) -> bool:
    """Both the person and the object moved over this step, and by nearly the same amount
    in nearly the same direction. Distances are scaled by the person's height."""
    scale = person_before.height
    if scale <= 0:
        return False
    (px0, py0), (px1, py1) = person_before.center, person_after.center
    (ox0, oy0), (ox1, oy1) = obj_before.center, obj_after.center
    person_dx, person_dy = px1 - px0, py1 - py0
    obj_dx, obj_dy = ox1 - ox0, oy1 - oy0
    person_step = math.hypot(person_dx, person_dy)
    obj_step = math.hypot(obj_dx, obj_dy)
    least = thresholds.min_moving_displacement * scale * frames
    if person_step < least or obj_step < least:
        return False
    mismatch = math.hypot(obj_dx - person_dx, obj_dy - person_dy)
    return mismatch <= thresholds.carry_motion_tolerance * person_step


def _offset_spread(pairs: list[tuple[BoundingBox, BoundingBox]]) -> float:
    """Widest range of the object's offset within the person's box, along either axis, in
    units of the person's size. 0 means the object never shifted relative to the person."""
    offsets = [relative_offset(person, obj) for person, obj in pairs]
    if not offsets:
        return 0.0
    xs = [x for x, _ in offsets]
    ys = [y for _, y in offsets]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def _carry_intervals(
    person: Track,
    person_boxes: dict[int, BoundingBox],
    obj: Track,
    thresholds: Thresholds,
) -> list[Interval]:
    """Carry intervals for one (person, object) pair."""
    longest_step = 1 + thresholds.gap_tolerance_frames
    # (frame, person box, object box, near) on every frame both tracks were seen.
    shared: list[tuple[int, BoundingBox, BoundingBox, bool]] = []
    for point in obj.points:
        person_box = person_boxes.get(point.frame)
        if person_box is not None:
            near = _is_near(point.box, person_box, thresholds)
            shared.append((point.frame, person_box, point.box, near))

    # One step per pair of consecutive shared frames close enough to compare.
    steps: list[tuple[int, int, bool]] = []
    for (f0, p0, o0, near0), (f1, p1, o1, near1) in zip(shared, shared[1:], strict=False):
        if f1 - f0 > longest_step:
            continue
        together = near0 and near1 and _moves_with(p0, p1, o0, o1, f1 - f0, thresholds)
        steps.append((f0, f1, together))
    if not any(together for _, _, together in steps):
        return []

    agreeing = ((f0, f1) for f0, f1, together in steps if together)
    step_starts = [f0 for f0, _, _ in steps]
    shared_frames = [frame for frame, _, _, _ in shared]
    intervals: list[Interval] = []
    for start, end in _join(agreeing, thresholds.gap_tolerance_frames):
        if end - start + 1 < thresholds.min_carry_frames:
            continue
        # Steps lie wholly inside a joined run: a run starts and ends on step endpoints.
        inside = steps[bisect_left(step_starts, start) : bisect_left(step_starts, end)]
        agreement = sum(1 for _, _, together in inside if together) / len(inside)
        if agreement < thresholds.carry_min_agreement:
            continue
        window = shared[bisect_left(shared_frames, start) : bisect_right(shared_frames, end)]
        held = [(p, o) for _, p, o, near in window if near]
        evidence = IntervalEvidence(
            "carrying",
            (person.track_id, obj.track_id),
            (
                ("frames_together", float(len(held))),
                ("motion_agreement", agreement),
                ("offset_spread", _offset_spread(held)),
            ),
        )
        intervals.append(Interval(start, end, evidence))
    return intervals


def carrying(
    person_tracks: Iterable[Track],
    box_tracks: Iterable[Track],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> list[Interval]:
    """Intervals where an object (a box_tracks track: cardboard box, bag or crate) was carried
    by a person.

    An object counts as carried over a run of frames when, step after step, its centre is
    inside or just outside the person's box (carry_near_margin, carry_containment) and it
    moves with the person: both actually move (min_moving_displacement) and by nearly the
    same displacement (carry_motion_tolerance). Runs separated by at most
    gap_tolerance_frames join into one; a run must span min_carry_frames and agree on
    carry_min_agreement of its steps. A box at rest beside a person, or a person walking
    past a box, does not move together and so is never carried. Neither is a person who
    stands still while holding something: there is no movement to compare, so a long pause
    splits a carry in two.

    Evidence: kind "carrying", track_ids (person, object), measures frames_together (frames
    the object was within reach), motion_agreement and offset_spread. Each pair is judged on
    its own, so two people walking side by side with one box can both match.
    """
    people = list(person_tracks)
    objects = list(box_tracks)
    person_boxes = [{p.frame: p.box for p in person.points} for person in people]
    intervals: list[Interval] = []
    for person, boxes in zip(people, person_boxes, strict=True):
        for obj in objects:
            if obj.last_frame < person.first_frame or person.last_frame < obj.first_frame:
                continue
            if (obj.track_id, obj.label) == (person.track_id, person.label):
                continue  # the same track given in both lists cannot carry itself
            intervals.extend(_carry_intervals(person, boxes, obj, thresholds))
    return _sorted(intervals)


# --- zones -------------------------------------------------------------------------------


def _inside_runs(
    track: Track, polygon: tuple[Point, ...], gap_tolerance: int
) -> list[tuple[int, int, int]]:
    """(start, end, frames inside) for each stretch the track's foot point was inside the
    polygon, joining stretches at most gap_tolerance frames apart. Frames where the track
    was not detected count neither way; they only widen the gap."""
    inside_frames = [p.frame for p in track.points if point_in_polygon(p.box.foot, polygon)]
    runs = _join(((f, f) for f in inside_frames), gap_tolerance)
    counted: list[tuple[int, int, int]] = []
    index = 0
    for start, end in runs:
        first = index
        while index < len(inside_frames) and inside_frames[index] <= end:
            index += 1
        counted.append((start, end, index - first))
    return counted


def region_traversal(
    tracks: Iterable[Track],
    polygon: Sequence[Point],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> list[Interval]:
    """Intervals where a track was inside a zone: from the first frame its foot point was
    seen inside (the entry) to the last frame before it left (the exit), both inclusive.

    Inside means the track's foot point (bottom-centre of its box) is inside the polygon, so
    a body that overlaps the zone while its feet stay outside does not count. A track first
    seen inside starts its interval there; one last seen inside ends it there. Leaving and
    coming back, or going undetected, within gap_tolerance_frames is one interval; longer
    is two. An interval must span min_zone_frames.

    Evidence: kind "in_zone", track_ids (track,), measures frames_inside, started_inside
    (1.0 if the track was already inside when first seen) and ended_inside (1.0 if it was
    still inside when last seen).
    """
    zone = _checked_polygon(polygon)
    intervals: list[Interval] = []
    for track in tracks:
        for start, end, inside in _inside_runs(track, zone, thresholds.gap_tolerance_frames):
            if end - start + 1 < thresholds.min_zone_frames:
                continue
            evidence = IntervalEvidence(
                "in_zone",
                (track.track_id,),
                (
                    ("frames_inside", float(inside)),
                    ("started_inside", 1.0 if start == track.first_frame else 0.0),
                    ("ended_inside", 1.0 if end == track.last_frame else 0.0),
                ),
            )
            intervals.append(Interval(start, end, evidence))
    return _sorted(intervals)


def dwell(
    tracks: Iterable[Track],
    polygon: Sequence[Point],
    min_frames: int,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> list[Interval]:
    """Intervals where a track stayed inside a zone for at least `min_frames` frames.

    Inside is judged by the foot point, as in region_traversal. Stepping out or going
    undetected for at most gap_tolerance_frames does not end the stay; the interval's span,
    gaps included, must reach min_frames. Turn a minimum time into frames with
    min_frames_for.

    Evidence: kind "dwell", track_ids (track,), measures frames_inside and coverage (the
    fraction of the interval's frames on which the foot point was seen inside).
    """
    _check_count("min_frames", min_frames, low=1)
    zone = _checked_polygon(polygon)
    intervals: list[Interval] = []
    for track in tracks:
        for start, end, inside in _inside_runs(track, zone, thresholds.gap_tolerance_frames):
            span = end - start + 1
            if span < min_frames:
                continue
            evidence = IntervalEvidence(
                "dwell",
                (track.track_id,),
                (("frames_inside", float(inside)), ("coverage", inside / span)),
            )
            intervals.append(Interval(start, end, evidence))
    return _sorted(intervals)


def region_entry(
    tracks: Iterable[Track],
    polygon: Sequence[Point],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> list[Interval]:
    """Intervals where a track crossed into a zone from outside.

    These are the region_traversal intervals of tracks that were seen outside the zone
    before going in: start_frame is the entry frame. A track first seen already inside
    never entered, so it gives nothing. Same evidence as region_traversal (kind "in_zone"),
    with started_inside always 0.0.
    """
    return [
        interval
        for interval in region_traversal(tracks, polygon, thresholds)
        if dict(interval.evidence.measures).get("started_inside") == 0.0
    ]
