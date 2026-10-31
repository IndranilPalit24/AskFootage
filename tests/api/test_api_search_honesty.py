"""Search over stored tracks says what it could not do, and its clips are real clips.

Covers: notes for a missing frame size, an unindexed concept, an unknown zone and an
unreadable track file; relation clip ids that GET /clips/{id} and POST /saved-clips accept;
clip times that never wrap past midnight; and the production wiring of the track store.
Tracks are built by hand; no perception, no network.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, time
from typing import Any

import pytest
from api_fakes import InMemoryLibrary, InMemoryTrackStore
from api_support import build_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_api_search_relations import (
    FRAME,
    REC,
    held_box,
    standing_person,
    walking_person,
)

from askfootage.application import search
from askfootage.application.library import Library
from askfootage.domain.tracks import Track
from askfootage.domain.vocabulary import ObjectNoun, Question
from askfootage.interfaces.api import app as app_module
from askfootage.ports.language_model import ParsedQuestion
from askfootage.settings import Settings

THURSDAY = date(2026, 10, 29)
CARRY = {"question": "someone carrying a box", "day": "2026-10-29", "camera": "CAM-001"}


class _Parser:
    def __init__(self, question: Question) -> None:
        self.question = question

    def parse(self, text: str) -> ParsedQuestion:
        return ParsedQuestion(self.question, "model")


def _search(
    store: InMemoryLibrary, tracks: Any, question: str, **extra: Any
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


@pytest.fixture
def tracks(store: InMemoryLibrary) -> InMemoryTrackStore:
    """An empty track store over the seeded library."""
    return InMemoryTrackStore(store)


@pytest.fixture
def carry_app(
    store: InMemoryLibrary, tracks: InMemoryTrackStore, fake_settings: Settings, videos_dir: Any
) -> FastAPI:
    """The API with one stored carry in REC."""
    tracks.save_tracks(REC, "person", [walking_person()])
    tracks.save_tracks(REC, "cardboard box", [held_box()])
    return build_app(store, fake_settings, videos_dir, tracks=tracks)


# --- Notes instead of silent fallbacks ----------------------------------------------------------


def test_a_zone_question_without_frame_size_says_so(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [standing_person()])
    result = _search(store, tracks, "someone waiting in the loading door", frame_size=None)
    assert result.proofs == ()
    assert result.note and "frame size" in result.note and REC in result.note


def test_a_concept_that_was_never_indexed_is_not_an_authoritative_empty_answer(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [walking_person()])  # no box tracks at all
    result = _search(store, tracks, "someone carrying a box")
    assert result.proofs == ()
    assert result.note and "cardboard box" in result.note and "not been indexed" in result.note
    assert REC in {found.clip.recording_id for found in result.clips}  # demo matcher answered


def test_an_unknown_zone_name_lists_the_known_zones(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [standing_person()])
    parser = _Parser(Question("dwell", ObjectNoun.PERSON, "Red jacket", 4.0))
    result = _search(store, tracks, "anything", parser=parser)
    assert result.proofs == ()
    assert result.note is not None
    assert "No zone named 'Red jacket'" in result.note
    assert "known zones: " in result.note and "Loading door" in result.note


def test_a_recording_with_an_unreadable_track_file_is_skipped(store: InMemoryLibrary) -> None:
    class Corrupt(InMemoryTrackStore):
        def tracks_for(self, video_id: str, label: str) -> list[Track]:
            raise ValueError("/srv/secret/tracks.json line 1 is not JSON")

    result = _search(store, Corrupt(store), "someone carrying a box")
    assert result.proofs == ()
    assert result.note and "could not be read" in result.note
    assert "/srv/" not in result.note and "secret" not in result.note
    assert len(result.clips) == 5  # the demo matcher answered


# --- Clip times ---------------------------------------------------------------------------------


def test_clip_start_time_past_midnight_stays_on_the_day(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    store.recordings[REC] = replace(store.recordings[REC], start_time=time(23, 59, 58))
    person, box = walking_person(frames=60), held_box(frames=60)
    late = {
        "person": Track(1, "person", tuple(p for p in person.points if p.frame >= 50)),
        "cardboard box": Track(7, "cardboard box", tuple(p for p in box.points if p.frame >= 50)),
    }
    for label, track in late.items():
        tracks.save_tracks(REC, label, [track])
    result = _search(store, tracks, "someone carrying a box")
    clip = next(found.clip for found in result.clips if found.clip.id.startswith("rel-"))
    assert clip.start_seconds >= 10
    assert clip.start_time == time(23, 59, 59)  # held at the end of the day, not 00:00:08


def test_clip_start_time_before_midnight_is_the_recording_start_plus_offset(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [walking_person()])
    tracks.save_tracks(REC, "cardboard box", [held_box()])
    clip = next(f.clip for f in _search(store, tracks, "someone carrying a box").clips)
    assert clip.id.startswith("rel-")
    assert clip.start_time == store.recordings[REC].start_time


# --- Relation clips are real clips --------------------------------------------------------------


def test_a_relation_clip_can_be_fetched_and_saved_over_http(carry_app: FastAPI) -> None:
    with TestClient(carry_app) as client:
        found = client.post("/api/search", json=CARRY).json()
        [proof] = found["proofs"]
        clip_id = proof["clipId"]
        assert clip_id.startswith("rel-")
        shown = client.get(f"/api/clips/{clip_id}")
        assert shown.status_code == 200, shown.text
        assert shown.json() == next(c for c in found["clips"] if c["id"] == clip_id)
        saved = client.post("/api/saved-clips", json={"clipId": clip_id, "note": "proof"})
        assert saved.status_code == 201, saved.text
        assert saved.json()["clip"]["id"] == clip_id
        again = client.post("/api/search", json=CARRY)
        assert again.status_code == 200  # the clip already exists: no duplicate error
        assert again.json()["proofs"][0]["clipId"] == clip_id
        assert client.post("/api/saved-clips", json={"clipId": clip_id}).status_code == 409


def test_an_unknown_relation_clip_id_is_still_a_404(carry_app: FastAPI) -> None:
    with TestClient(carry_app) as client:
        assert client.get("/api/clips/rel-0000000000000000").status_code == 404


def test_a_stored_relation_clip_is_not_a_demo_match_once_its_tracks_are_gone(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    tracks.save_tracks(REC, "person", [walking_person()])
    tracks.save_tracks(REC, "cardboard box", [held_box()])
    first = _search(store, tracks, "someone carrying a box")
    assert any(f.clip.id.startswith("rel-") for f in first.clips)
    tracks.delete_video(REC)
    second = _search(store, tracks, "someone carrying a box")
    assert not any(f.clip.id.startswith("rel-") for f in second.clips)


# --- Production wiring --------------------------------------------------------------------------


class _SizedStore(InMemoryTrackStore):
    def frame_size(self, video_id: str) -> tuple[float, float] | None:
        return FRAME if video_id == REC else None


def test_the_frame_size_comes_from_the_track_store_when_not_given(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Any
) -> None:
    sized = _SizedStore(store)
    sized.save_tracks(REC, "person", [standing_person(frames=50)])
    app = build_app(store, fake_settings, videos_dir, tracks=sized)
    question = {**CARRY, "question": "someone waiting in the loading door for 8 seconds"}
    with TestClient(app) as client:
        body = client.post("/api/search", json=question).json()
    assert [proof["relation"] for proof in body["proofs"]] == ["dwell"]


def _rows(track: Track) -> list[dict[str, Any]]:
    points = [[p.frame, p.box.x1, p.box.y1, p.box.x2, p.box.y2] for p in track.points]
    return [{"track_id": track.track_id, "points": points}]


def test_the_factory_serves_stored_tracks_from_the_data_dir(
    fake_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "load_settings", lambda: fake_settings)
    folder = fake_settings.data_dir / REC
    folder.mkdir(parents=True)
    stored = {"person": _rows(walking_person()), "cardboard box": _rows(held_box())}
    (folder / "tracks.json").write_text(json.dumps(stored), encoding="utf-8")
    with TestClient(app_module.create_app()) as client:
        body = client.post("/api/search", json=CARRY).json()
        [proof] = body["proofs"]
        assert proof["relation"] == "carrying"
        assert client.get(f"/api/clips/{proof['clipId']}").status_code == 200
    assert "sk-test" not in json.dumps(body)


def test_the_factory_wires_the_json_store_only_in_production_mode(
    fake_settings: Settings, monkeypatch: pytest.MonkeyPatch, store: InMemoryLibrary
) -> None:
    monkeypatch.setattr(app_module, "load_settings", lambda: fake_settings)
    production = app_module.create_app()
    assert production.state.context.tracks is not None
    injected = app_module.create_app(fake_settings, library=Library.from_store(store))
    assert injected.state.context.tracks is None


def test_the_ports_track_data_error_skips_the_recording_with_a_fixed_note(
    store: InMemoryLibrary,
) -> None:
    from askfootage.ports.track_store import TrackDataError

    class Damaged(InMemoryTrackStore):
        def tracks_for(self, video_id: str, label: str) -> list[Track]:
            raise TrackDataError("fixed message")

    result = _search(store, Damaged(store), "someone carrying a box")
    assert result.proofs == () and result.note and "could not be read" in result.note
    assert len(result.clips) == 5


def test_a_damaged_frame_size_is_treated_as_unknown(
    store: InMemoryLibrary, tracks: InMemoryTrackStore
) -> None:
    from askfootage.ports.track_store import TrackDataError

    def broken(video_id: str) -> tuple[float, float]:
        raise TrackDataError("fixed message")

    tracks.save_tracks(REC, "person", [standing_person()])
    result = _search(store, tracks, "someone waiting in the loading door", frame_size=broken)
    assert result.note and "frame size" in result.note
