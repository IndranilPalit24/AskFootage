"""region_entry: a track crossing into a zone from outside."""

from askfootage.domain.models import BoundingBox, Point
from askfootage.domain.relations import region_entry
from askfootage.domain.tracks import Track, TrackPoint

ZONE: tuple[Point, ...] = ((100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0))
INSIDE: Point = (200.0, 200.0)
OUTSIDE: Point = (50.0, 200.0)


def _pattern(track_id: int, pattern: str) -> Track:
    points = []
    for i, c in enumerate(pattern):
        if c == ".":
            continue
        x, y = INSIDE if c == "I" else OUTSIDE
        points.append(TrackPoint(i, BoundingBox(x - 20, y - 100, x + 20, y)))
    return Track(track_id, "person", tuple(points))


def test_crossing_in_from_outside_is_an_entry_at_the_first_inside_frame() -> None:
    result = region_entry([_pattern(1, "OOOIIII")], ZONE)
    assert [(i.start_frame, i.end_frame, i.evidence.track_ids) for i in result] == [(3, 6, (1,))]
    assert result[0].evidence.kind == "in_zone"


def test_a_track_first_seen_inside_never_entered() -> None:
    assert region_entry([_pattern(1, "IIII")], ZONE) == []


def test_a_track_that_stays_outside_has_no_entry() -> None:
    assert region_entry([_pattern(1, "OOOO")], ZONE) == []


def test_a_single_frame_flicker_is_not_an_entry() -> None:
    assert region_entry([_pattern(1, "OOOIOOOO")], ZONE) == []


def test_each_separate_entry_is_reported() -> None:
    result = region_entry([_pattern(1, "OOIIIOOOOOOIII")], ZONE)
    assert [(i.start_frame, i.end_frame) for i in result] == [(2, 4), (11, 13)]


def test_empty_input_gives_nothing() -> None:
    assert region_entry([], ZONE) == []


def test_order_of_tracks_does_not_matter() -> None:
    a, b = _pattern(1, "OOIII"), _pattern(2, "OOOII")
    assert region_entry([a, b], ZONE) == region_entry([b, a], ZONE)
