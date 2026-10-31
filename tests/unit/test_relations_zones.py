"""Region traversal and dwell on synthetic tracks, judged by each track's foot point."""

import random

import pytest

from askfootage.domain.intervals import Interval
from askfootage.domain.models import BoundingBox, Point
from askfootage.domain.relations import (
    DEFAULT_THRESHOLDS,
    Thresholds,
    dwell,
    min_frames_for,
    region_traversal,
)
from askfootage.domain.timebase import Timebase
from askfootage.domain.tracks import Track, TrackPoint

ZONE: tuple[Point, ...] = ((100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0))
INSIDE: Point = (200.0, 200.0)
OUTSIDE: Point = (50.0, 200.0)
GAP = DEFAULT_THRESHOLDS.gap_tolerance_frames


def _box_with_foot(foot: Point) -> BoundingBox:
    """A 40 x 100 person box standing on `foot`."""
    x, y = foot
    return BoundingBox(x - 20, y - 100, x + 20, y)


def _track(track_id: int, feet: dict[int, Point], label: str = "person") -> Track:
    points = tuple(TrackPoint(f, _box_with_foot(feet[f])) for f in sorted(feet))
    return Track(track_id, label, points)


def _pattern(track_id: int, pattern: str, first_frame: int = 0) -> Track:
    """One character per frame: I = foot inside the zone, O = outside, . = not detected."""
    feet = {
        first_frame + i: INSIDE if c == "I" else OUTSIDE for i, c in enumerate(pattern) if c != "."
    }
    return _track(track_id, feet)


def _spans(intervals: list[Interval]) -> list[tuple[int, int, tuple[int, ...]]]:
    return [(i.start_frame, i.end_frame, i.evidence.track_ids) for i in intervals]


# --- region traversal --------------------------------------------------------------------


def test_walking_through_the_zone_gives_enter_and_exit_frames() -> None:
    # The foot moves 20 px a frame along y=200: x=110 on frame 5 to x=290 on frame 14.
    walker = _track(3, {f: (20.0 * f + 10, 200.0) for f in range(21)})
    result = region_traversal([walker], ZONE)
    assert _spans(result) == [(5, 14, (3,))]
    evidence = result[0].evidence
    assert evidence.kind == "in_zone"
    assert evidence.measures == (
        ("frames_inside", 10.0),
        ("started_inside", 0.0),
        ("ended_inside", 0.0),
    )


def test_a_track_that_starts_inside_and_leaves() -> None:
    result = region_traversal([_pattern(1, "IIIIIOOOO", first_frame=3)], ZONE)
    assert _spans(result) == [(3, 7, (1,))]
    assert dict(result[0].evidence.measures)["started_inside"] == 1.0
    assert dict(result[0].evidence.measures)["ended_inside"] == 0.0


def test_a_track_that_ends_inside() -> None:
    result = region_traversal([_pattern(1, "OOOIIII")], ZONE)
    assert _spans(result) == [(3, 6, (1,))]
    assert dict(result[0].evidence.measures)["ended_inside"] == 1.0


def test_leaving_and_re_entering_beyond_the_gap_tolerance_gives_two_intervals() -> None:
    track = _pattern(1, "IIII" + "O" * (GAP + 1) + "IIII")
    assert _spans(region_traversal([track], ZONE)) == [(0, 3, (1,)), (GAP + 5, GAP + 8, (1,))]


def test_stepping_out_within_the_gap_tolerance_is_one_interval() -> None:
    track = _pattern(1, "IIII" + "O" * GAP + "IIII")
    result = region_traversal([track], ZONE)
    assert _spans(result) == [(0, GAP + 7, (1,))]
    assert dict(result[0].evidence.measures)["frames_inside"] == 8.0


def test_missing_frames_within_the_gap_tolerance_do_not_split() -> None:
    track = _pattern(1, "IIII" + "." * GAP + "IIII")
    assert _spans(region_traversal([track], ZONE)) == [(0, GAP + 7, (1,))]


def test_missing_frames_beyond_the_gap_tolerance_split() -> None:
    track = _pattern(1, "IIII" + "." * (GAP + 1) + "IIII")
    assert len(region_traversal([track], ZONE)) == 2


def test_grazing_the_zone_edge_with_the_body_but_not_the_feet_is_not_inside() -> None:
    # Feet 30 px below the zone: the box overlaps the zone and its centre is inside it.
    feet = {f: (120.0 + 15 * f, 330.0) for f in range(12)}
    grazer = _track(2, feet)
    assert grazer.points[0].box.center[1] < 300
    assert region_traversal([grazer], ZONE) == []
    assert dwell([grazer], ZONE, min_frames=1) == []


def test_a_single_frame_flicker_across_the_edge_is_ignored() -> None:
    assert region_traversal([_pattern(1, "OOOIOOO")], ZONE) == []
    min_zone = DEFAULT_THRESHOLDS.min_zone_frames
    track = _pattern(1, "OOO" + "I" * min_zone + "OOO")
    assert _spans(region_traversal([track], ZONE)) == [(3, 2 + min_zone, (1,))]


def test_a_track_that_never_enters_gives_nothing() -> None:
    assert region_traversal([_pattern(1, "OOOOOO")], ZONE) == []
    assert region_traversal([], ZONE) == []


def test_concave_zone_uses_the_true_shape() -> None:
    # An L-shape: the notch at the top right is outside.
    l_shape = ((0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (50.0, 50.0), (50.0, 100.0), (0.0, 100.0))
    notch = _track(1, {f: (75.0, 75.0) for f in range(5)})
    leg = _track(2, {f: (25.0, 75.0) for f in range(5)})
    assert _spans(region_traversal([notch, leg], l_shape)) == [(0, 4, (2,))]


def test_traversal_output_is_sorted_and_independent_of_input_order() -> None:
    tracks = [
        _pattern(4, "OOIIIOO"),
        _pattern(2, "OOIIIOO"),
        _pattern(9, "IIIIOOOOOOOOIII"),
        _pattern(1, "OOOOOIIIII"),
    ]
    expected = region_traversal(tracks, ZONE)
    assert _spans(expected) == [
        (0, 3, (9,)),
        (2, 4, (2,)),
        (2, 4, (4,)),
        (5, 9, (1,)),
        (12, 14, (9,)),
    ]
    rng = random.Random(3)
    for _ in range(10):
        rng.shuffle(tracks)
        assert region_traversal(tracks, ZONE) == expected


@pytest.mark.parametrize(
    "polygon",
    [(), ((0.0, 0.0), (1.0, 1.0)), ((0.0, 0.0), (1.0, float("nan")), (2.0, 0.0))],
)
def test_a_bad_polygon_is_refused_even_with_no_tracks(polygon: tuple[Point, ...]) -> None:
    with pytest.raises(ValueError):
        region_traversal([], polygon)
    with pytest.raises(ValueError):
        dwell([], polygon, min_frames=1)


# --- dwell -------------------------------------------------------------------------------


def test_inside_for_exactly_min_frames_is_a_dwell() -> None:
    result = dwell([_pattern(5, "OO" + "I" * 10 + "OO")], ZONE, min_frames=10)
    assert _spans(result) == [(2, 11, (5,))]
    evidence = result[0].evidence
    assert evidence.kind == "dwell"
    assert evidence.measures == (("frames_inside", 10.0), ("coverage", 1.0))


def test_inside_for_one_frame_less_than_min_frames_is_not() -> None:
    assert dwell([_pattern(5, "OO" + "I" * 9 + "OO")], ZONE, min_frames=10) == []


def test_a_short_step_out_within_tolerance_still_counts_toward_dwell() -> None:
    track = _pattern(1, "IIIII" + "O" * GAP + "II")
    result = dwell([track], ZONE, min_frames=7 + GAP)
    assert _spans(result) == [(0, 6 + GAP, (1,))]
    assert result[0].evidence.measures == (
        ("frames_inside", 7.0),
        ("coverage", 7.0 / (7 + GAP)),
    )


def test_a_step_out_beyond_tolerance_breaks_the_dwell() -> None:
    track = _pattern(1, "IIIIII" + "O" * (GAP + 1) + "IIIIII")
    assert dwell([track], ZONE, min_frames=7) == []
    assert len(dwell([track], ZONE, min_frames=6)) == 2


def test_hidden_frames_within_tolerance_still_count_toward_dwell() -> None:
    track = _pattern(1, "IIIII" + "." * GAP + "II")
    assert _spans(dwell([track], ZONE, min_frames=7 + GAP)) == [(0, 6 + GAP, (1,))]


def test_custom_gap_tolerance_is_honoured() -> None:
    track = _pattern(1, "IIIII" + "O" + "IIII")
    assert dwell([track], ZONE, 10, Thresholds(gap_tolerance_frames=0)) == []
    assert len(dwell([track], ZONE, 10, Thresholds(gap_tolerance_frames=1))) == 1


def test_dwell_minimum_from_seconds_at_the_edge() -> None:
    timebase = Timebase(5.0)
    min_frames = min_frames_for(10.0, timebase)
    assert min_frames == 50
    stayed = _pattern(1, "I" * 50)
    short = _pattern(2, "I" * 49)
    result = dwell([stayed, short], ZONE, min_frames)
    assert _spans(result) == [(0, 49, (1,))]
    assert result[0].seconds(timebase) == pytest.approx((0.0, 10.0))


@pytest.mark.parametrize(("seconds", "frames"), [(0.0, 1), (0.1, 1), (0.2, 1), (0.21, 2)])
def test_min_frames_for_is_at_least_one(seconds: float, frames: int) -> None:
    assert min_frames_for(seconds, Timebase(5.0)) == frames


@pytest.mark.parametrize("min_frames", [0, -3, True, 2.5])
def test_dwell_refuses_a_bad_minimum(min_frames: int) -> None:
    with pytest.raises((ValueError, TypeError)):
        dwell([_pattern(1, "IIII")], ZONE, min_frames)


def test_dwell_output_is_independent_of_input_order() -> None:
    tracks = [_pattern(i, "O" * (i % 4) + "I" * (6 + i)) for i in range(8)]
    expected = dwell(tracks, ZONE, min_frames=9)
    assert [i.evidence.track_ids for i in expected] == [(4,), (5,), (6,), (3,), (7,)]
    rng = random.Random(11)
    for _ in range(10):
        rng.shuffle(tracks)
        assert dwell(tracks, ZONE, min_frames=9) == expected


def test_a_track_given_twice_does_not_duplicate_intervals() -> None:
    track = _pattern(1, "OIIIIO")
    assert region_traversal([track, track], ZONE) == region_traversal([track], ZONE)
    assert dwell([track, track], ZONE, 3) == dwell([track], ZONE, 3)


def test_same_id_under_different_labels_stays_separate() -> None:
    feet = {f: INSIDE for f in range(4)}
    person = _track(1, feet)
    bag = _track(1, {f + 4: INSIDE for f in range(4)}, label="bag")
    assert _spans(region_traversal([person, bag], ZONE)) == [(0, 3, (1,)), (4, 7, (1,))]
