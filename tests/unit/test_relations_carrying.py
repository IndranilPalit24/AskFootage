"""The carrying rule on synthetic tracks: what counts as carried and what must not."""

import random
from collections.abc import Callable

from askfootage.domain.intervals import Interval
from askfootage.domain.models import BoundingBox
from askfootage.domain.relations import DEFAULT_THRESHOLDS, Thresholds, carrying
from askfootage.domain.tracks import Track, TrackPoint

PERSON_W, PERSON_H = 60.0, 180.0
"""A person's box: 60 x 180 px, top at y=100, so the feet are at y=280."""

MIN = DEFAULT_THRESHOLDS.min_carry_frames


def _person_box(x: float, y: float = 100.0) -> BoundingBox:
    return BoundingBox(x, y, x + PERSON_W, y + PERSON_H)


def _held_box(x: float, y: float = 100.0) -> BoundingBox:
    """A 30 x 40 box held at chest height in front of a person whose box starts at x."""
    return BoundingBox(x + 15, y + 60, x + 45, y + 100)


def _floor_box(x: float) -> BoundingBox:
    """A 30 x 30 box resting on the floor, its bottom at y=280."""
    return BoundingBox(x, 250, x + 30, 280)


def _track(
    track_id: int, label: str, frames: range | list[int], box_at: Callable[[int], BoundingBox]
) -> Track:
    return Track(track_id, label, tuple(TrackPoint(f, box_at(f)) for f in frames))


def _walker(track_id: int, frames: range | list[int], speed: float = 10.0) -> Track:
    return _track(track_id, "person", frames, lambda f: _person_box(speed * f))


def _carried(track_id: int, frames: range | list[int], speed: float = 10.0) -> Track:
    return _track(track_id, "cardboard box", frames, lambda f: _held_box(speed * f))


def _spans(intervals: list[Interval]) -> list[tuple[int, int, tuple[int, ...]]]:
    return [(i.start_frame, i.end_frame, i.evidence.track_ids) for i in intervals]


# --- the positive case -------------------------------------------------------------------


def test_a_box_held_by_a_walking_person_is_carried() -> None:
    result = carrying([_walker(1, range(30))], [_carried(7, range(30))])
    assert _spans(result) == [(0, 29, (1, 7))]
    evidence = result[0].evidence
    assert evidence.kind == "carrying"
    measures = dict(evidence.measures)
    assert [name for name, _ in evidence.measures] == [
        "frames_together",
        "motion_agreement",
        "offset_spread",
    ]
    assert measures["frames_together"] == 30.0
    assert measures["motion_agreement"] == 1.0
    assert measures["offset_spread"] == 0.0


def test_a_box_picked_up_and_put_down_is_carried_only_in_between() -> None:
    person = _walker(1, range(50), speed=8.0)

    def box_at(f: int) -> BoundingBox:
        if f < 10:
            return _floor_box(8.0 * 10 + 15)  # waiting where the person will pick it up
        if f <= 35:
            return _held_box(8.0 * f)
        return _held_box(8.0 * 35)  # set down where it was last held, then left behind

    result = carrying([person], [_track(3, "cardboard box", range(50), box_at)])
    assert _spans(result) == [(10, 35, (1, 3))]


# --- negatives ---------------------------------------------------------------------------


def test_a_person_walking_past_empty_handed_is_not_carrying() -> None:
    far_box = _track(5, "cardboard box", range(30), lambda f: _floor_box(2000))
    assert carrying([_walker(1, range(30))], [far_box]) == []
    assert carrying([_walker(1, range(30))], []) == []


def test_a_box_on_the_floor_beside_a_standing_person_is_not_carried() -> None:
    person = _track(1, "person", range(60), lambda f: _person_box(100))
    box = _track(2, "cardboard box", range(60), lambda f: _floor_box(120))
    assert carrying([person], [box]) == []


def test_a_person_walking_slowly_past_a_box_on_the_floor_is_not_carrying() -> None:
    # 4 px a frame keeps the floor box inside the person's reach for about 20 frames.
    person = _walker(1, range(60), speed=4.0)
    box = _track(2, "cardboard box", range(60), lambda f: _floor_box(120))
    assert carrying([person], [box]) == []


def test_camera_shake_moving_both_together_is_not_carrying() -> None:
    def shake(f: int) -> float:
        return 1.0 if f % 2 else 0.0

    person = _track(1, "person", range(60), lambda f: _person_box(100 + shake(f)))
    box = _track(2, "cardboard box", range(60), lambda f: _held_box(100 + shake(f)))
    assert carrying([person], [box]) == []


def test_a_box_moving_on_its_own_past_a_standing_person_is_not_carried() -> None:
    person = _track(1, "person", range(60), lambda f: _person_box(100))
    box = _track(
        2, "cardboard box", range(60), lambda f: BoundingBox(115, 60 + 4 * f, 145, 90 + 4 * f)
    )
    assert carrying([person], [box]) == []


def test_a_box_pushed_along_in_jerks_out_of_step_with_the_person_is_not_carried() -> None:
    def box_at(f: int) -> BoundingBox:
        return _held_box(24.0 * ((f + 1) // 2))  # 24 px, then 0, then 24 ... vs 12 a frame

    person = _walker(1, range(40), speed=12.0)
    assert carrying([person], [_track(2, "cardboard box", range(40), box_at)]) == []


def test_a_box_with_no_person_present_is_not_carried() -> None:
    moving_box = _carried(2, range(40))
    assert carrying([], [moving_box]) == []
    elsewhere = _track(1, "person", range(40), lambda f: _person_box(3000))
    assert carrying([elsewhere], [moving_box]) == []


def test_a_person_and_box_on_different_frames_never_pair() -> None:
    assert carrying([_walker(1, range(0, 20))], [_carried(2, range(20, 40))]) == []


# --- min frames boundary -----------------------------------------------------------------


def test_carried_for_exactly_min_frames_counts() -> None:
    result = carrying([_walker(1, range(MIN))], [_carried(2, range(MIN))])
    assert _spans(result) == [(0, MIN - 1, (1, 2))]


def test_carried_for_one_frame_less_than_min_frames_does_not() -> None:
    assert carrying([_walker(1, range(MIN - 1))], [_carried(2, range(MIN - 1))]) == []


# --- gaps --------------------------------------------------------------------------------


def test_box_missing_for_frames_within_the_gap_tolerance_stays_one_carry() -> None:
    gap = DEFAULT_THRESHOLDS.gap_tolerance_frames
    frames = [f for f in range(30) if not 10 <= f < 10 + gap]
    result = carrying([_walker(1, range(30))], [_carried(2, frames)])
    assert _spans(result) == [(0, 29, (1, 2))]
    assert dict(result[0].evidence.measures)["frames_together"] == 30.0 - gap


def test_box_missing_for_longer_than_the_gap_tolerance_splits_the_carry() -> None:
    gap = DEFAULT_THRESHOLDS.gap_tolerance_frames
    frames = [f for f in range(40) if not 12 <= f <= 12 + gap]
    result = carrying([_walker(1, range(40))], [_carried(2, frames)])
    assert _spans(result) == [(0, 11, (1, 2)), (13 + gap, 39, (1, 2))]


def test_a_brief_stumble_within_the_gap_tolerance_does_not_split_the_carry() -> None:
    def box_at(f: int) -> BoundingBox:
        return _held_box(10.0 * f + (40.0 if f == 15 else 0.0))  # one frame jolts away

    person = _walker(1, range(30))
    result = carrying([person], [_track(2, "cardboard box", range(30), box_at)])
    assert _spans(result) == [(0, 29, (1, 2))]
    assert dict(result[0].evidence.measures)["motion_agreement"] == 27 / 29


def test_with_no_gap_tolerance_a_stumble_splits_the_carry() -> None:
    def box_at(f: int) -> BoundingBox:
        return _held_box(10.0 * f + (40.0 if f == 15 else 0.0))

    strict = Thresholds(gap_tolerance_frames=0)
    person = _walker(1, range(30))
    result = carrying([person], [_track(2, "cardboard box", range(30), box_at)], strict)
    assert _spans(result) == [(0, 14, (1, 2)), (16, 29, (1, 2))]


# --- several tracks and determinism ------------------------------------------------------


def test_only_the_person_holding_the_box_carries_it() -> None:
    holder = _walker(1, range(30))
    beside = _track(2, "person", range(30), lambda f: _person_box(10.0 * f, y=600))
    result = carrying([beside, holder], [_carried(9, range(30))])
    assert _spans(result) == [(0, 29, (1, 9))]


def test_one_person_carrying_two_boxes_gives_two_intervals_ordered_by_track() -> None:
    person = _walker(4, range(30))
    second = _track(8, "bag", range(5, 30), lambda f: _held_box(10.0 * f))
    result = carrying([person], [second, _carried(6, range(30))])
    assert _spans(result) == [(0, 29, (4, 6)), (5, 29, (4, 8))]


def test_shuffled_input_gives_identical_output() -> None:
    persons = [_walker(i, range(40)) for i in (1, 2)]
    persons.append(_track(3, "person", range(40), lambda f: _person_box(100)))
    boxes = [
        _carried(10, range(40)),
        _track(11, "cardboard box", range(40), lambda f: _floor_box(120)),
        _track(12, "bag", range(10, 40), lambda f: _held_box(10.0 * f)),
    ]
    expected = carrying(persons, boxes)
    assert len(expected) >= 2
    rng = random.Random(7)
    for _ in range(10):
        rng.shuffle(persons)
        rng.shuffle(boxes)
        assert carrying(persons, boxes) == expected
    starts = [(i.start_frame, i.evidence.track_ids) for i in expected]
    assert starts == sorted(starts)


def test_a_track_never_carries_itself() -> None:
    walker = _walker(1, range(30))
    assert carrying([walker], [walker]) == []


def test_a_track_given_twice_does_not_duplicate_intervals() -> None:
    person, box = _walker(1, range(30)), _carried(2, range(30))
    assert carrying([person, person], [box, box]) == carrying([person], [box])


def test_a_box_moving_across_the_persons_path_is_not_carried() -> None:
    # Both move 6 px a frame, the person to the right and the box straight down (say, on a
    # chute); the box stays within reach on frames 6 to 18 but never moves with the person.
    person = _walker(1, range(30), speed=6.0)
    box = _track(
        2, "cardboard box", range(30), lambda f: BoundingBox(90, 110 + 6 * f, 110, 130 + 6 * f)
    )
    assert carrying([person], [box]) == []
