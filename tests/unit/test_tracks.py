"""Track and TrackPoint: validation and frame lookups, including gaps."""

import pytest

from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint

BOX = BoundingBox(0, 0, 10, 10)


def _track(*frames: int, label: str = "person") -> Track:
    return Track(track_id=1, label=label, points=tuple(TrackPoint(f, BOX) for f in frames))


def test_first_last_and_frames_with_a_gap() -> None:
    track = _track(3, 4, 9)
    assert (track.first_frame, track.last_frame, track.frames) == (3, 9, (3, 4, 9))


def test_box_at_returns_the_box_only_on_frames_present() -> None:
    other = BoundingBox(1, 2, 3, 4)
    track = Track(1, "person", (TrackPoint(2, BOX), TrackPoint(5, other)))
    assert track.box_at(5) == other
    assert track.box_at(2) == BOX
    assert [track.box_at(f) for f in (0, 3, 4, 6)] == [None, None, None, None]
    assert track.has_frame(5) and not track.has_frame(4)


def test_tracks_compare_by_value() -> None:
    assert _track(1, 2) == _track(1, 2)
    assert hash(_track(1, 2)) == hash(_track(1, 2))


@pytest.mark.parametrize("frames", [(), (2, 2), (3, 1)])
def test_points_must_be_non_empty_and_strictly_increasing(frames: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        _track(*frames)


@pytest.mark.parametrize("label", ["", "  ", " person", "x" * 41])
def test_label_must_be_trimmed_non_blank_and_short(label: str) -> None:
    with pytest.raises(ValueError):
        _track(1, label=label)


def test_frame_must_be_a_non_negative_int() -> None:
    with pytest.raises(ValueError):
        TrackPoint(-1, BOX)
    with pytest.raises(TypeError):
        TrackPoint(True, BOX)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        TrackPoint(1.0, BOX)  # type: ignore[arg-type]


def test_track_id_must_be_a_non_negative_int() -> None:
    with pytest.raises(ValueError):
        Track(-1, "person", (TrackPoint(0, BOX),))
    with pytest.raises(TypeError):
        Track("1", "person", (TrackPoint(0, BOX),))  # type: ignore[arg-type]


def test_box_at_on_a_long_track() -> None:
    track = _track(*range(0, 10_000, 2))
    assert track.box_at(9_998) == BOX
    assert track.box_at(9_999) is None
