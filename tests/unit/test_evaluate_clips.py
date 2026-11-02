"""Comparing the seconds-based clip labels with what the relation layer finds in stored tracks."""

from collections.abc import Sequence

import pytest

from askfootage.application.clip_labels import ClipEvent, ClipLabels
from askfootage.application.evaluate_clips import evaluate_clip
from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint


class Tracks:
    def __init__(self, found: dict[str, list[Track]]) -> None:
        self.found = found

    def tracks_for(self, video_id: str, label: str) -> list[Track]:
        return self.found.get(label, [])


def walker(label: str, track_id: int, frames: range, dx: float, x0: float, y: float, size: float):
    points = tuple(
        TrackPoint(f, BoundingBox(x0 + dx * f, y, x0 + dx * f + size, y + size * 2)) for f in frames
    )
    return Track(track_id, label, points)


def labels(*events: ClipEvent) -> ClipLabels:
    return ClipLabels("clipX", tuple(events))


def carrying_scene(frames: range) -> Tracks:
    person = walker("person", 0, frames, 20.0, 100.0, 100.0, 100.0)
    box = walker("cardboard box", 0, frames, 20.0, 130.0, 160.0, 40.0)
    return Tracks({"person": [person], "cardboard box": [box]})


def row_of(result, kind: str):
    return next(r for r in result.rows if r.event.type == kind)


def test_a_confirmed_carry_that_is_found_is_a_match() -> None:
    event = ClipEvent("carrying", "box", 1.0, 5.0, "confirmed")
    result = evaluate_clip(labels(event), carrying_scene(range(5, 25)), "clipX")
    row = row_of(result, "carrying")
    assert row.verdict == "match"
    assert row.found == ((1.0, 5.0),)
    assert row.iou == pytest.approx(1.0)


def test_a_confirmed_carry_that_is_not_found_is_a_miss() -> None:
    event = ClipEvent("carrying", "box", 1.0, 5.0, "confirmed")
    result = evaluate_clip(labels(event), Tracks({"person": [], "cardboard box": []}), "clipX")
    row = row_of(result, "carrying")
    assert row.verdict == "miss"
    assert row.found == ()


def test_an_unconfirmed_event_is_shown_but_never_scored() -> None:
    event = ClipEvent("in_frame", "person", 1.0, 7.0, "unconfirmed")
    result = evaluate_clip(labels(event), carrying_scene(range(0, 40)), "clipX")
    row = row_of(result, "in_frame")
    assert row.verdict == "not scored"
    assert row.found == ((0.0, 8.0),)
    assert result.scored == 0


def test_in_frame_is_the_time_the_person_was_tracked() -> None:
    event = ClipEvent("in_frame", "person", 0.0, 8.0, "confirmed")
    result = evaluate_clip(labels(event), carrying_scene(range(0, 40)), "clipX")
    assert row_of(result, "in_frame").verdict == "match"


def test_leaves_room_has_no_rule_and_is_reported_as_such() -> None:
    event = ClipEvent("leaves_room", "box", 6.0, 6.0, "confirmed")
    result = evaluate_clip(labels(event), carrying_scene(range(5, 25)), "clipX")
    row = row_of(result, "leaves_room")
    assert row.verdict == "not evaluable"
    assert "no rule" in row.note
    assert result.scored == 0


def test_the_note_gives_when_the_object_was_last_seen() -> None:
    event = ClipEvent("leaves_room", "box", 6.0, 6.0, "confirmed")
    note = row_of(
        evaluate_clip(labels(event), carrying_scene(range(5, 25)), "clipX"), "leaves_room"
    ).note
    assert "last seen" in note and "4.8" in note


def test_a_found_carry_in_the_wrong_place_is_a_miss() -> None:
    event = ClipEvent("carrying", "box", 6.0, 8.0, "confirmed")
    result = evaluate_clip(labels(event), carrying_scene(range(5, 25)), "clipX")
    assert row_of(result, "carrying").verdict == "miss"


def test_summary_counts_scored_rows_and_matches() -> None:
    events: Sequence[ClipEvent] = (
        ClipEvent("carrying", "box", 1.0, 5.0, "confirmed"),
        ClipEvent("leaves_room", "box", 6.0, 6.0, "confirmed"),
    )
    result = evaluate_clip(labels(*events), carrying_scene(range(5, 25)), "clipX")
    assert (result.scored, result.matched) == (1, 1)
