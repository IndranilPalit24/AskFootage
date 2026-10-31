"""Joining track fragments and adjacent relation intervals."""

import pytest

from askfootage.domain.intervals import Interval, IntervalEvidence
from askfootage.domain.models import BoundingBox
from askfootage.domain.stitching import (
    DEFAULT_STITCH,
    StitchParams,
    merge_intervals,
    stitch_tracks,
)
from askfootage.domain.tracks import Track, TrackPoint


def _track(
    track_id: int, frames: range, x0: float = 0.0, label: str = "person", dx: float = 2.0
) -> Track:
    pts = tuple(
        TrackPoint(f, BoundingBox(x0 + dx * i, 0, x0 + dx * i + 40, 100))
        for i, f in enumerate(frames)
    )
    return Track(track_id, label, pts)


def test_params_validate() -> None:
    with pytest.raises(ValueError):
        StitchParams(max_gap_frames=-1)
    with pytest.raises(ValueError):
        StitchParams(max_center_shift=-0.1)


def test_two_close_fragments_become_one_track_with_the_first_id() -> None:
    a = _track(5, range(0, 10))
    b = _track(9, range(12, 20), x0=24.0)
    merged = stitch_tracks([b, a])
    assert len(merged) == 1
    assert merged[0].track_id == 5
    assert merged[0].first_frame == 0 and merged[0].last_frame == 19
    assert len(merged[0].points) == 18


def test_a_long_time_gap_keeps_fragments_apart() -> None:
    a, b = _track(1, range(0, 5)), _track(2, range(60, 65), x0=10.0)
    assert len(stitch_tracks([a, b])) == 2


def test_a_far_jump_keeps_fragments_apart() -> None:
    a, b = _track(1, range(0, 5)), _track(2, range(6, 10), x0=900.0)
    assert len(stitch_tracks([a, b])) == 2


def test_different_labels_never_merge() -> None:
    a, b = _track(1, range(0, 5)), _track(2, range(6, 10), x0=10.0, label="bag")
    assert len(stitch_tracks([a, b])) == 2


def test_overlapping_fragments_never_merge() -> None:
    a, b = _track(1, range(0, 10)), _track(2, range(5, 15), x0=10.0)
    assert len(stitch_tracks([a, b])) == 2


def test_three_fragments_chain() -> None:
    a = _track(1, range(0, 5))
    b = _track(2, range(6, 11), x0=12.0)
    c = _track(3, range(12, 17), x0=24.0)
    merged = stitch_tracks([c, a, b])
    assert [t.track_id for t in merged] == [1]
    assert merged[0].last_frame == 16


def test_empty_and_order_independent() -> None:
    assert stitch_tracks([]) == []
    a, b = _track(1, range(0, 5)), _track(2, range(6, 10), x0=10.0)
    assert stitch_tracks([a, b]) == stitch_tracks([b, a])


def test_default_params_are_the_documented_ones() -> None:
    assert DEFAULT_STITCH == StitchParams()


def _iv(
    start: int,
    end: int,
    kind: str = "dwell",
    ids: tuple[int, ...] = (1,),
    measures: tuple[tuple[str, float], ...] = (),
) -> Interval:
    return Interval(start, end, IntervalEvidence(kind, ids, measures))  # type: ignore[arg-type]


def test_adjacent_intervals_merge() -> None:
    out = merge_intervals([_iv(0, 4), _iv(5, 9)])
    assert [(i.start_frame, i.end_frame) for i in out] == [(0, 9)]


def test_gap_within_tolerance_merges_and_beyond_does_not() -> None:
    assert len(merge_intervals([_iv(0, 4), _iv(7, 9)], max_gap_frames=2)) == 1
    assert len(merge_intervals([_iv(0, 4), _iv(8, 9)], max_gap_frames=2)) == 2


def test_overlapping_intervals_merge_regardless_of_order() -> None:
    out = merge_intervals([_iv(5, 12), _iv(0, 8)])
    assert [(i.start_frame, i.end_frame) for i in out] == [(0, 12)]


def test_different_kind_or_tracks_do_not_merge() -> None:
    assert len(merge_intervals([_iv(0, 4), _iv(5, 9, kind="in_zone")])) == 2
    assert len(merge_intervals([_iv(0, 4), _iv(5, 9, ids=(2,))])) == 2


def test_frame_measures_are_summed_and_flags_follow_the_ends() -> None:
    a = _iv(0, 4, measures=(("frames_inside", 5.0), ("started_inside", 1.0), ("ended_inside", 0.0)))
    b = _iv(5, 9, measures=(("frames_inside", 3.0), ("started_inside", 0.0), ("ended_inside", 1.0)))
    (merged,) = merge_intervals([a, b])
    values = dict(merged.evidence.measures)
    assert values == {"frames_inside": 8.0, "started_inside": 1.0, "ended_inside": 1.0}


def test_other_measures_are_frame_weighted_means() -> None:
    a = _iv(0, 2, measures=(("coverage", 1.0),))
    b = _iv(3, 4, measures=(("coverage", 0.0),))
    (merged,) = merge_intervals([a, b])
    assert dict(merged.evidence.measures)["coverage"] == pytest.approx(0.6)


def test_empty_and_negative_gap() -> None:
    assert merge_intervals([]) == []
    with pytest.raises(ValueError):
        merge_intervals([_iv(0, 1)], max_gap_frames=-1)


def test_total_shift_is_capped_at_two_box_sizes_however_long_the_gap() -> None:
    # box is 100 high: larger side. Gap of 15 frames would allow 0.25*100*16 = 400 px
    # by the per-frame rule, but the absolute cap is 2 box sizes = 200 px.
    a = _track(1, range(0, 5))
    near = _track(2, range(20, 25), x0=8 + 150.0)
    far = _track(3, range(20, 25), x0=8 + 260.0)
    assert len(stitch_tracks([a, near])) == 1
    assert len(stitch_tracks([a, far])) == 2


def test_shift_cap_parameter_validates_and_can_be_tightened() -> None:
    with pytest.raises(ValueError):
        StitchParams(max_shift_boxes=-1)
    a = _track(1, range(0, 5))
    near = _track(2, range(20, 25), x0=8 + 150.0)
    assert len(stitch_tracks([a, near], StitchParams(max_shift_boxes=1.0))) == 2
