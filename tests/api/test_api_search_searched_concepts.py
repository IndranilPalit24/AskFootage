"""A noun that was searched for and found nothing is an answer, not "not indexed".

Clip 1 of the real footage has a person but no box. The box pass ran and came back empty, so
"a person carrying a box" is judged from the tracks (no carry) and the recording is not
sent to the demo matcher with a note that claims the box was never indexed.
"""

from __future__ import annotations

from datetime import date

from api_fakes import InMemoryLibrary, InMemoryTrackStore
from test_api_search_relations import REC, _search, walking_person

from askfootage.application import search
from askfootage.application.library import Library


def tracks_for(store: InMemoryLibrary) -> InMemoryTrackStore:
    return InMemoryTrackStore(store)


def test_a_searched_empty_noun_is_judged_not_unindexed(store: InMemoryLibrary) -> None:
    tracks = tracks_for(store)
    tracks.save_tracks(REC, "person", [walking_person()])
    tracks.save_tracks(REC, "cardboard box", [])  # searched, nothing found
    result = _search(store, tracks, "someone carrying a box")
    assert REC not in {c.clip.recording_id for c in result.clips}
    assert "not been indexed" not in (result.note or "")


def test_a_noun_never_searched_is_still_reported_as_unindexed(store: InMemoryLibrary) -> None:
    tracks = tracks_for(store)
    tracks.save_tracks(REC, "person", [walking_person()])
    result = _search(store, tracks, "someone carrying a box")
    assert "cardboard box has not been indexed" in (result.note or "")


def test_the_demo_clip_of_a_judged_recording_is_not_used(store: InMemoryLibrary) -> None:
    tracks = tracks_for(store)
    tracks.save_tracks(REC, "person", [walking_person()])
    tracks.save_tracks(REC, "cardboard box", [])
    result = search.search_day(
        Library.from_store(store),
        search.QuestionInterpreter(),
        "someone carrying a box",
        date(2026, 10, 29),
        "CAM-001",
        tracks=tracks,
        frame_size=lambda video_id: (1000.0, 1000.0),
    )
    assert all(c.clip.recording_id != REC for c in result.clips)
