import pytest

from askfootage.domain.timebase import Timebase, format_timecode


@pytest.mark.parametrize(("frame", "seconds"), [(0, 0.0), (1, 0.2), (5, 1.0), (50, 10.0)])
def test_frame_to_seconds_at_five_fps(frame: int, seconds: float) -> None:
    assert Timebase(fps=5).frame_to_seconds(frame) == pytest.approx(seconds)


@pytest.mark.parametrize("fps", [5.0, 25.0, 29.97])
def test_every_frame_survives_a_round_trip(fps: float) -> None:
    # Naive floor(seconds * fps) fails thousands of these at 25 and 29.97 fps.
    timebase = Timebase(fps=fps)
    for frame in range(100_000):
        assert timebase.seconds_to_frame(timebase.frame_to_seconds(frame)) == frame


def test_a_time_inside_a_frame_maps_to_that_frame() -> None:
    assert Timebase(fps=5).seconds_to_frame(0.39) == 1


def test_frame_count_for_rounds_up_so_a_threshold_is_never_under_counted() -> None:
    assert Timebase(fps=5).frame_count_for(10.0) == 50
    assert Timebase(fps=5).frame_count_for(0.1) == 1


@pytest.mark.parametrize("fps", [0, -5, float("nan"), float("inf")])
def test_rejects_an_unusable_frame_rate(fps: float) -> None:
    with pytest.raises(ValueError, match="fps"):
        Timebase(fps=fps)


def test_rejects_a_negative_frame() -> None:
    with pytest.raises(ValueError, match="frame"):
        Timebase().frame_to_seconds(-1)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00.0"), (12.4, "00:12.4"), (59.96, "00:59.9"), (75.25, "01:15.2")],
)
def test_format_timecode(seconds: float, expected: str) -> None:
    assert format_timecode(seconds) == expected
