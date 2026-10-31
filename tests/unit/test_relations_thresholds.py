"""Relation thresholds: named defaults, validation, and speed on a large synthetic input."""

import dataclasses
import math
import time
from collections.abc import Callable

import pytest

from askfootage.domain.models import BoundingBox, Point
from askfootage.domain.relations import (
    DEFAULT_THRESHOLDS,
    Thresholds,
    carrying,
    dwell,
    region_traversal,
)
from askfootage.domain.tracks import Track, TrackPoint

# --- defaults and validation -------------------------------------------------------------


def test_defaults_are_the_documented_values() -> None:
    assert dataclasses.asdict(DEFAULT_THRESHOLDS) == {
        "carry_near_margin": 0.15,
        "carry_containment": 0.5,
        "min_carry_frames": 10,
        "min_moving_displacement": 0.02,
        "carry_motion_tolerance": 0.5,
        "carry_min_agreement": 0.6,
        "gap_tolerance_frames": 3,
        "min_zone_frames": 2,
    }
    assert Thresholds() == DEFAULT_THRESHOLDS


def test_thresholds_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_THRESHOLDS.min_carry_frames = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"carry_near_margin": -0.1},
        {"carry_near_margin": math.inf},
        {"carry_containment": 1.5},
        {"carry_containment": -0.1},
        {"carry_containment": math.nan},
        {"min_carry_frames": 0},
        {"min_carry_frames": 2.5},
        {"min_carry_frames": True},
        {"min_moving_displacement": 0.0},
        {"min_moving_displacement": -1.0},
        {"carry_motion_tolerance": -0.5},
        {"carry_motion_tolerance": math.inf},
        {"carry_min_agreement": 0.0},
        {"carry_min_agreement": 1.01},
        {"gap_tolerance_frames": -1},
        {"gap_tolerance_frames": 1.0},
        {"min_zone_frames": 0},
    ],
)
def test_out_of_range_thresholds_are_refused(kwargs: dict[str, float]) -> None:
    with pytest.raises((ValueError, TypeError)):
        Thresholds(**kwargs)  # type: ignore[arg-type]


def test_boundary_thresholds_are_accepted() -> None:
    Thresholds(
        carry_near_margin=0.0,
        carry_containment=0.0,
        min_carry_frames=1,
        carry_motion_tolerance=0.0,
        carry_min_agreement=1.0,
        gap_tolerance_frames=0,
        min_zone_frames=1,
    )


# --- large input -------------------------------------------------------------------------

FRAMES = 2_000
LANES = 10
ZONE: tuple[Point, ...] = ((300.0, 0.0), (900.0, 0.0), (900.0, 5000.0), (300.0, 5000.0))
TIME_LIMIT_SECONDS = 1.0


def _x(frame: int, lane: int) -> float:
    """Walk back and forth over 0..1200 px at 8 px a frame, each lane at its own phase."""
    phase = (frame * 8 + lane * 97) % 2400
    return float(phase if phase <= 1200 else 2400 - phase)


def _large_scene() -> tuple[list[Track], list[Track]]:
    """10 people walking back and forth in their own lanes; even lanes carry a box and odd
    lanes have a box resting on the floor of their lane. Every track is detected on every
    frame except a short dropout every 97 frames."""
    persons: list[Track] = []
    boxes: list[Track] = []
    for lane in range(LANES):
        top = 400.0 * lane
        frames = [f for f in range(FRAMES) if f % 97 not in (50, 51)]
        persons.append(
            Track(
                lane,
                "person",
                tuple(
                    TrackPoint(f, BoundingBox(_x(f, lane), top, _x(f, lane) + 60, top + 180))
                    for f in frames
                ),
            )
        )

        def box_at(f: int, lane: int = lane, top: float = top) -> BoundingBox:
            if lane % 2 == 0:
                return BoundingBox(_x(f, lane) + 15, top + 60, _x(f, lane) + 45, top + 100)
            return BoundingBox(600, top + 150, 630, top + 180)

        boxes.append(
            Track(100 + lane, "cardboard box", tuple(TrackPoint(f, box_at(f)) for f in frames))
        )
    return persons, boxes


def _timed[T](run: Callable[[], T]) -> tuple[T, float]:
    start = time.perf_counter()
    result = run()
    return result, time.perf_counter() - start


def test_large_input_runs_within_a_second_per_rule() -> None:
    persons, boxes = _large_scene()
    assert len(persons) + len(boxes) == 20

    carried, carry_seconds = _timed(lambda: carrying(persons, boxes))
    crossed, cross_seconds = _timed(lambda: region_traversal(persons + boxes, ZONE))
    stayed, dwell_seconds = _timed(lambda: dwell(persons + boxes, ZONE, min_frames=200))

    assert carry_seconds < TIME_LIMIT_SECONDS, carry_seconds
    assert cross_seconds < TIME_LIMIT_SECONDS, cross_seconds
    assert dwell_seconds < TIME_LIMIT_SECONDS, dwell_seconds

    pairs = {i.evidence.track_ids for i in carried}
    assert pairs == {(lane, 100 + lane) for lane in range(0, LANES, 2)}
    covered = sum(i.frame_count for i in carried)
    assert covered >= 0.95 * FRAMES * LANES / 2

    # Each walker crosses the zone about 3 times each way; the resting boxes stay put.
    assert len(crossed) > 50
    resting = [i for i in stayed if i.evidence.track_ids[0] >= 100]
    assert {i.evidence.track_ids for i in resting} == {(100 + lane,) for lane in range(1, 10, 2)}
