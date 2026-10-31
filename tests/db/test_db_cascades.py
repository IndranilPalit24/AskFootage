"""Deleting a parent removes its dependants and leaves no orphans; hostile text is just text."""

from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest
from db_library_helpers import (
    CAM_1,
    CAM_2,
    TABLES,
    clip,
    count_rows,
    new_camera,
    raw_connection,
    recording,
    track,
    zone,
)

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.adapters.sqlite.tracks import SqliteTrackStore
from askfootage.ports.library_store import Evidence, KeyFrame

INJECTION = "x'); DROP TABLE zones;--"


@pytest.fixture
def full(store: SqliteLibraryStore, library_path: Path) -> Path:
    """Two cameras, each with a recording, a clip (with evidence and key frames), a saved
    clip, a zone and two tracks of three points, so a cascade can be told apart from a
    wipe."""
    tracks = SqliteTrackStore(store)
    for index in (1, 2):
        camera_id = store.add_camera(new_camera(f"Camera {index}")).id
        store.add_recording(recording(f"rec-{index}", camera_id))
        store.add_clip(
            clip(
                f"clip-{index}",
                f"rec-{index}",
                evidence=(Evidence("carrying", "Carrying"), Evidence("dwell", "Stayed")),
                key_frames=(KeyFrame(5), KeyFrame(10), KeyFrame(15)),
            )
        )
        store.add_saved_clip(
            f"saved-{index}", f"clip-{index}", "", datetime(2026, 10, 30, tzinfo=UTC)
        )
        store.add_zone(zone(f"zone-{index}", camera_id))
        tracks.save_tracks(f"rec-{index}", "person", [track(1), track(2)])
    return library_path


def _counts(path: Path) -> dict[str, int]:
    return {table: count_rows(path, table) for table in TABLES}


def _assert_no_orphans(path: Path) -> None:
    with raw_connection(path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


ONE_CAMERA_LEFT = {
    "camera_sequence": 1,
    "cameras": 1,
    "recordings": 1,
    "clips": 1,
    "clip_evidence": 2,
    "clip_key_frames": 3,
    "zones": 1,
    "zone_points": 4,
    "saved_clips": 1,
    "tracks": 2,
    "track_points": 6,
}


def test_deleting_a_recording_removes_its_clips_and_everything_hanging_off_them(
    full: Path,
) -> None:
    with raw_connection(full) as db:
        db.execute("DELETE FROM recordings WHERE id = ?", ("rec-1",))

    assert _counts(full) == {
        "camera_sequence": 1,
        "cameras": 2,
        "recordings": 1,
        "clips": 1,
        "clip_evidence": 2,
        "clip_key_frames": 3,
        "zones": 2,  # zones belong to the camera, not the recording
        "zone_points": 8,
        "saved_clips": 1,
        "tracks": 2,
        "track_points": 6,
    }
    _assert_no_orphans(full)
    store = SqliteLibraryStore(full)
    assert store.get_clip("clip-1") is None and store.get_saved_clip("saved-1") is None
    assert store.get_clip("clip-2") is not None


def test_deleting_a_camera_row_removes_its_recordings_clips_and_zones(full: Path) -> None:
    """The schema cascades on its own, whoever deletes the camera."""
    with raw_connection(full) as db:
        db.execute("DELETE FROM cameras WHERE id = ?", (CAM_1,))

    assert _counts(full) == ONE_CAMERA_LEFT
    _assert_no_orphans(full)
    assert [z.id for z in SqliteLibraryStore(full).list_zones()] == ["zone-2"]


def test_delete_camera_removes_everything_on_it_and_leaves_the_other_camera_alone(
    full: Path,
) -> None:
    store = SqliteLibraryStore(full)
    day = date(2026, 10, 29)
    other_before = (
        store.get_camera(CAM_2),
        store.list_recordings(CAM_2, day),
        store.list_clips(CAM_2, day),
        store.list_zones(CAM_2),
        store.get_saved_clip("saved-2"),
    )

    assert store.delete_camera(CAM_1) is True

    assert _counts(full) == ONE_CAMERA_LEFT
    _assert_no_orphans(full)
    assert store.get_camera(CAM_1) is None
    assert store.get_recording("rec-1") is None
    assert store.get_clip("clip-1") is None
    assert store.get_zone("zone-1") is None
    assert store.get_saved_clip("saved-1") is None
    assert store.list_recordings(CAM_1, day) == [] and store.list_clips(CAM_1, day) == []
    other_after = (
        store.get_camera(CAM_2),
        store.list_recordings(CAM_2, day),
        store.list_clips(CAM_2, day),
        store.list_zones(CAM_2),
        store.get_saved_clip("saved-2"),
    )
    assert other_after == other_before
    assert [s.id for s in store.list_saved_clips()] == ["saved-2"]
    assert list(store.camera_counts()) == [CAM_2]


def test_delete_camera_twice_or_unknown_changes_nothing(full: Path) -> None:
    store = SqliteLibraryStore(full)
    assert store.delete_camera(CAM_1) is True
    before = _counts(full)

    assert store.delete_camera(CAM_1) is False
    assert store.delete_camera("CAM-009") is False

    assert _counts(full) == before


def test_deleting_a_clip_removes_its_evidence_key_frames_and_saved_entry(full: Path) -> None:
    with raw_connection(full) as db:
        db.execute("DELETE FROM clips WHERE id = ?", ("clip-2",))

    counts = _counts(full)
    assert (counts["clips"], counts["clip_evidence"], counts["clip_key_frames"]) == (1, 2, 3)
    assert counts["saved_clips"] == 1
    _assert_no_orphans(full)


def test_deleting_a_saved_clip_through_the_store_leaves_the_clip(full: Path) -> None:
    store = SqliteLibraryStore(full)
    assert store.delete_saved_clip("saved-1") is True
    counts = _counts(full)
    assert (counts["saved_clips"], counts["clips"], counts["clip_evidence"]) == (1, 2, 4)


def test_deleting_a_zone_through_the_store_removes_only_its_points(full: Path) -> None:
    assert SqliteLibraryStore(full).delete_zone("zone-2") is True
    counts = _counts(full)
    assert (counts["zones"], counts["zone_points"], counts["cameras"]) == (1, 4, 2)
    _assert_no_orphans(full)


def test_an_injection_string_is_stored_as_plain_text(full: Path) -> None:
    store = SqliteLibraryStore(full)
    added = store.add_camera(new_camera(INJECTION))
    store.add_zone(zone("zone-3", CAM_1, name=INJECTION))
    store.add_clip(
        clip(
            "clip-3",
            "rec-1",
            start_time=time(10, 1),
            start_seconds=60,
            end_seconds=61,
            label=INJECTION,
            zone=INJECTION,
        )
    )
    store.add_saved_clip("saved-3", "clip-3", INJECTION, datetime(2026, 10, 30, tzinfo=UTC))
    store.replace_zone(zone("zone-2", CAM_2, name=INJECTION + " again"))
    store.update_note("saved-1", "'; DELETE FROM saved_clips; --")

    assert store.get_zone("zone-3") == zone("zone-3", CAM_1, name=INJECTION)
    assert store.get_camera(added.id) == added and added.name == INJECTION
    saved = store.get_saved_clip("saved-3")
    assert saved is not None and saved.note == INJECTION and saved.clip.label == INJECTION
    first = store.get_saved_clip("saved-1")
    assert first is not None and first.note == "'; DELETE FROM saved_clips; --"
    # Hostile ids are refused by validation, and lookups with them simply find nothing.
    assert store.get_zone(INJECTION) is None
    assert store.delete_zone(INJECTION) is False
    assert store.list_zones(INJECTION) == []
    assert store.get_camera(INJECTION) is None
    assert store.delete_camera(INJECTION) is False
    assert store.list_recordings(INJECTION, date(2026, 10, 29)) == []

    with raw_connection(full) as db:
        tables = {
            row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
        }
    assert tables == set(TABLES)
    assert _counts(full)["saved_clips"] == 3
    assert _counts(full)["cameras"] == 3
    assert len(store.list_zones()) == 3
