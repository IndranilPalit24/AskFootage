"""Interval and IntervalEvidence: validation, inclusive frame counts and seconds at the edge."""

import math

import pytest

from askfootage.domain.intervals import Interval, IntervalEvidence
from askfootage.domain.timebase import Timebase

WHY = IntervalEvidence("carrying", (1, 2), (("frames_together", 12.0),))


def test_frames_are_inclusive_at_both_ends() -> None:
    assert Interval(5, 5, WHY).frame_count == 1
    assert Interval(5, 9, WHY).frame_count == 5


def test_seconds_run_to_the_end_of_the_last_frame() -> None:
    assert Interval(10, 14, WHY).seconds(Timebase(5.0)) == (2.0, 3.0)


@pytest.mark.parametrize(("start", "end"), [(-1, 3), (4, 3)])
def test_bad_frame_ranges_are_rejected(start: int, end: int) -> None:
    with pytest.raises(ValueError):
        Interval(start, end, WHY)


def test_evidence_rejects_unknown_kind_no_tracks_and_bad_measures() -> None:
    with pytest.raises(ValueError):
        IntervalEvidence("teleport", (1,))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        IntervalEvidence("dwell", ())
    with pytest.raises(ValueError):
        IntervalEvidence("dwell", (1,), (("", 1.0),))
    with pytest.raises(ValueError):
        IntervalEvidence("dwell", (1,), (("x", math.nan),))
