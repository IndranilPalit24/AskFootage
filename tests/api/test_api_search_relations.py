"""Search over stored tracks: the relation layer answers, the demo keyword matcher is the fallback.

Tracks are built by hand (no perception, no network). The frame is 1000 x 1000 px, so the
seeded "Loading door" zone on CAM-001 (fractions 0.06-0.44 wide, 0.2-0.9 high) is the pixel
box roughly x 60-440, y 200-900.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from api_fakes import InMemoryLibrary, InMemoryTrackStore, load_example
from api_support import build_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from askfootage.application import search
from askfootage.application.library import Library
from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint
from askfootage.domain.vocabulary import ObjectNoun, Question
from askfootage.ports.language_model import ParsedQuestion, QuestionNotUnderstoodError
from askfootage.settings import Settings

THURSDAY = date(2026, 10, 29)
REC = "rec-1029-0600"
FRAME = (1000.0, 1000.0)


def _track(track_id: int, label: str, boxes: dict[int, tuple[float, float, float, float]]) -> Track:
    points = tuple(TrackPoint(frame, BoundingBox(*box)) for frame, box in sorted(boxes.items()))
    return Track(track_id, label, points)


def walking_person(track_id: int = 1, start_x: float = 100.0, frames: int = 25) -> Track:
    """A 100 x 300 person moving right 10 px a frame; the feet are at the box's bottom."""
    return _track(
        track_id,
        "person",
        {f: (start_x + 10 * f, 500.0, start_x + 100 + 10 * f, 800.0) for f in range(frames)},
    )


def held_box(track_id: int = 7, start_x: float = 100.0, frames: int = 25) -> Track:
    """A 40 x 40 box held at the person's chest, moving with them."""
    return _track(
        track_id,
        "cardboard box",
        {f: (start_x + 30 + 10 * f, 600.0, start_x + 70 + 10 * f, 640.0) for f in range(frames)},
    )


def standing_person(track_id: int = 3, frames: int = 50) -> Track:
    """A person standing at x 150-250, feet at (200, 800), inside the Loading door zone."""
    return _track(track_id, "person", {f: (150.0, 500.0, 250.0, 800.0) for f in range(frames)})


@pytest.fixture
def tracks(store: InMemoryLibrary) -> InMemoryTrackStore:
    """An empty track store over the seeded library."""
    return InMemoryTrackStore(store)


def _search(
    store: InMemoryLibrary, tracks: InMemoryTrackStore | None, question: str, **extra: Any
) -> search.SearchResult:
    options: dict[str, Any] = {"tracks": tracks, "frame_size": lambda video_id: FRAME}
    options.update(extra)
    return search.search_day(
        Library.from_store(store),
        search.QuestionInterpreter(),
        question,
        THURSDAY,
        "CAM-001",
        **options,
    )


def _relation_clips(result: search.SearchResult) -> list[str]:
    return [found.clip.id for found in result.clips if found.clip.id.startswith("rel-")]


# --- Carrying ---------------------------------------------------------------------------------


def test_carrying_over_stored_tracks_returns_a_clip_with_proof(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [walking_person()])
    tracks.save_tracks(REC, "cardboard box", [held_box()])
    result = _search(store, tracks, "someone carrying a box")
    mine = [c for c in result.clips if c.clip.recording_id == REC]
    assert len(mine) == 1 and len(result.proofs) == 1
    found, proof = mine[0], result.proofs[0]
    assert found.camera == "CAM-001" and found.clip.recording_id == REC
    assert proof.clip_id == found.clip.id
    assert proof.relation == "carrying"
    assert proof.track_ids == (1, 7) and proof.track_labels == ("person", "cardboard box")
    assert (proof.start_frame, proof.end_frame) == (0, 24)
    assert proof.start_seconds == pytest.approx(0.0)
    assert proof.end_seconds == pytest.approx(25 / 5)
    assert {name for name, _ in proof.measures} >= {"frames_together", "motion_agreement"}
    assert proof.boxes and all(box.frame in range(25) for box in proof.boxes)
    assert {box.track_id for box in proof.boxes} == {1, 7}
    assert found.clip.evidence[0].kind == "carrying"
    assert found.clip.start_seconds == 0 and found.clip.end_seconds == 5


def test_the_relation_path_replaces_the_demo_clips_for_a_video_with_tracks(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [walking_person()])
    tracks.save_tracks(REC, "cardboard box", [held_box()])
    result = _search(store, tracks, "someone carrying a box")
    demo_in_rec = [
        c for c in result.clips if c.clip.recording_id == REC and c.clip.id[:4] != "rel-"
    ]
    assert demo_in_rec == []  # the stored demo clip of this recording is not used
    other = {c.clip.recording_id for c in result.clips} - {REC}
    assert other  # videos without stored tracks still answer from the demo clips


def test_a_stored_video_with_no_carry_gives_no_clips_not_the_demo_clip(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    resting_box = _track(7, "cardboard box", {f: (130.0, 600.0, 170.0, 640.0) for f in range(25)})
    tracks.save_tracks(REC, "person", [walking_person()])
    tracks.save_tracks(REC, "cardboard box", [resting_box])
    result = _search(store, tracks, "someone carrying a box")
    assert REC not in {c.clip.recording_id for c in result.clips}
    assert result.proofs == ()


def test_fragmented_tracks_are_stitched_before_the_relation_runs(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    person = walking_person()
    box = held_box()
    first = Track(7, "cardboard box", box.points[:12])
    second = Track(8, "cardboard box", box.points[13:])  # one frame missed, a new id
    tracks.save_tracks(REC, "person", [person])
    tracks.save_tracks(REC, "cardboard box", [first, second])
    result = _search(store, tracks, "someone carrying a box")
    proofs = [p for p in result.proofs if p.relation == "carrying"]
    assert len(proofs) == 1 and proofs[0].track_ids == (1, 7)


# --- Zones --------------------------------------------------------------------------------------


def test_entering_a_zone_gives_an_entry_interval_with_the_zone_name(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [walking_person(start_x=-200.0, frames=50)])
    result = _search(store, tracks, "someone entering the loading door")
    assert len(result.proofs) == 1
    proof = result.proofs[0]
    assert proof.relation == "in_zone" and proof.track_ids == (1,)
    assert proof.start_frame > 0
    clip = result.clips[0].clip
    assert clip.zone == "Loading door"
    assert [e.kind for e in clip.evidence] == ["in_zone"]


def test_a_person_already_inside_never_entered(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [standing_person()])
    assert _search(store, tracks, "someone entering the loading door").proofs == ()


def test_dwell_needs_the_asked_minimum_time(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [standing_person(frames=50)])  # 10 s at 5 fps
    long_enough = _search(store, tracks, "someone waiting in the loading door for 8 seconds")
    assert [p.relation for p in long_enough.proofs] == ["dwell"]
    assert long_enough.clips[0].clip.zone == "Loading door"
    too_long = _search(store, tracks, "someone waiting in the loading door for 20 seconds")
    assert too_long.proofs == ()


def test_a_zone_question_without_frame_size_falls_back_to_the_demo_matcher(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [standing_person()])
    result = _search(store, tracks, "someone waiting in the loading door", frame_size=None)
    assert result.proofs == ()


# --- Fallbacks ---------------------------------------------------------------------------------


def test_without_a_track_store_it_is_the_demo_search(store: InMemoryLibrary) -> None:
    result = _search(store, None, "someone carrying a box")
    assert len(result.clips) == 5 and result.proofs == ()


def test_a_question_with_no_relation_uses_the_demo_matcher(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [walking_person()])
    result = _search(store, tracks, "anyone around")
    assert result.proofs == ()
    assert len(result.clips) == 8  # every ready clip


def test_unrecognised_questions_keep_the_not_understood_note(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    result = _search(store, tracks, "purple elephants")
    assert result.clips == [] and result.note and "did not recognise" in result.note


# --- The injected parser -----------------------------------------------------------------------


class _Parser:
    def __init__(self, question: Question | None) -> None:
        self.question = question
        self.asked: list[str] = []

    def parse(self, text: str) -> ParsedQuestion:
        self.asked.append(text)
        if self.question is None:
            raise QuestionNotUnderstoodError("no")
        return ParsedQuestion(self.question, "model")


def test_an_injected_parser_is_used_before_the_keyword_reader(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [standing_person(frames=50)])
    parser = _Parser(Question("dwell", ObjectNoun.PERSON, "Loading door", 4.0))
    result = _search(store, tracks, "zzz nothing the keyword reader knows", parser=parser)
    assert parser.asked == ["zzz nothing the keyword reader knows"]
    assert [p.relation for p in result.proofs] == ["dwell"]


def test_a_parser_that_does_not_understand_falls_back_to_the_keyword_reader(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [walking_person()])
    tracks.save_tracks(REC, "cardboard box", [held_box()])
    result = _search(store, tracks, "someone carrying a box", parser=_Parser(None))
    assert [p.relation for p in result.proofs] == ["carrying"]


# --- Over HTTP ---------------------------------------------------------------------------------


@pytest.fixture
def relation_app(
    store: InMemoryLibrary, tracks: InMemoryTrackStore, fake_settings: Settings, videos_dir: Any
) -> FastAPI:
    """The API with a track store that holds one carry."""
    tracks.save_tracks(REC, "person", [walking_person()])
    tracks.save_tracks(REC, "cardboard box", [held_box()])
    return build_app(
        store, fake_settings, videos_dir, tracks=tracks, frame_size=lambda video_id: FRAME
    )


def test_the_http_response_carries_the_proof(relation_app: FastAPI) -> None:
    with TestClient(relation_app) as client:
        response = client.post(
            "/api/search",
            json={"question": "someone carrying a box", "day": "2026-10-29", "camera": "CAM-001"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    [proof] = body["proofs"]
    clip = next(c for c in body["clips"] if c["id"] == proof["clipId"])
    assert clip["recordingId"] == REC
    assert proof["relation"] == "carrying"
    assert proof["trackIds"] == [1, 7] and proof["trackLabels"] == ["person", "cardboard box"]
    assert proof["startFrame"] == 0 and proof["endFrame"] == 24
    assert set(proof) == {
        "clipId",
        "relation",
        "startFrame",
        "endFrame",
        "startSeconds",
        "endSeconds",
        "trackIds",
        "trackLabels",
        "measures",
        "boxes",
    }
    assert set(proof["measures"][0]) == {"name", "value"}
    assert set(proof["boxes"][0]) == {"frame", "trackId", "label", "x1", "y1", "x2", "y2"}
    text = response.text
    assert "/srv/" not in text and "sk-test" not in text


def test_demo_answers_have_an_empty_proofs_list(client: TestClient) -> None:
    response = client.post(
        "/api/search",
        json={"question": "someone carrying a box", "day": "2026-10-29", "camera": "CAM-001"},
    )
    assert response.json() == load_example("search-response.json")
    assert response.json()["proofs"] == []


def test_a_track_store_that_fails_is_a_clean_500(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Any
) -> None:
    class Broken(InMemoryTrackStore):
        def tracks_for(self, video_id: str, label: str) -> list[Track]:
            raise RuntimeError("/srv/askfootage/private-data exploded")

    app = build_app(
        store,
        fake_settings,
        videos_dir,
        tracks=Broken(store),
        frame_size=lambda video_id: FRAME,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/search",
            json={"question": "someone carrying a box", "day": "2026-10-29"},
        )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "private-data" not in response.text


def test_recording_with_a_changed_status_is_not_searched(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [walking_person()])
    tracks.save_tracks(REC, "cardboard box", [held_box()])
    store.recordings[REC] = replace(store.recordings[REC], status="indexing")
    result = _search(store, tracks, "someone carrying a box")
    assert result.proofs == ()
