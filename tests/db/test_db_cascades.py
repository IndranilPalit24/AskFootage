"""Deleting a parent removes its dependants and leaves no orphans; hostile text is just text."""

from datetime import UTC, datetime, time
from pathlib import Path

import pytest
from db_library_helpers import TABLES, camera, clip, count_rows, raw_connection, recording, zone

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.ports.library_store import Evidence, KeyFrame

INJECTION = "x'); DROP TABLE zones;--"


@pytest.fixture
def full(store: SqliteLibraryStore, library_path: Path) -> Path:
    """Two cameras, each with a recording, a clip (with evidence and key frames), a saved
    clip and a zone, so a cascade can be told apart from a wipe."""
    for index in (1, 2):
        store.add_camera(camera(f"cam-{index}", f"Camera {index}"))
        store.add_recording(recording(f"rec-{index}", f"cam-{index}"))
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
        store.add_zone(zone(f"zone-{index}", f"cam-{index}"))
    return library_path


def _counts(path: Path) -> dict[str, int]:
    return {table: count_rows(path, table) for table in TABLES}


def _assert_no_orphans(path: Path) -> None:
    with raw_connection(path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_deleting_a_recording_removes_its_clips_and_everything_hanging_off_them(
    full: Path,
) -> None:
    with raw_connection(full) as db:
        db.execute("DELETE FROM recordings WHERE id = ?", ("rec-1",))

    assert _counts(full) == {
        "cameras": 2,
        "recordings": 1,
        "clips": 1,
        "clip_evidence": 2,
        "clip_key_frames": 3,
        "zones": 2,  # zones belong to the camera, not the recording
        "zone_points": 8,
        "saved_clips": 1,
    }
    _assert_no_orphans(full)
    store = SqliteLibraryStore(full)
    assert store.get_clip("clip-1") is None and store.get_saved_clip("saved-1") is None
    assert store.get_clip("clip-2") is not None


def test_deleting_a_camera_removes_its_recordings_clips_and_zones(full: Path) -> None:
    with raw_connection(full) as db:
        db.execute("DELETE FROM cameras WHERE id = ?", ("cam-1",))

    assert _counts(full) == {
        "cameras": 1,
        "recordings": 1,
        "clips": 1,
        "clip_evidence": 2,
        "clip_key_frames": 3,
        "zones": 1,
        "zone_points": 4,
        "saved_clips": 1,
    }
    _assert_no_orphans(full)
    assert [z.id for z in SqliteLibraryStore(full).list_zones()] == ["zone-2"]


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
    store.add_camera(camera("cam-3", INJECTION))
    store.add_zone(zone("zone-3", "cam-1", name=INJECTION))
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
    store.replace_zone(zone("zone-2", "cam-2", name=INJECTION + " again"))
    store.update_note("saved-1", "'; DELETE FROM saved_clips; --")

    assert store.get_zone("zone-3") == zone("zone-3", "cam-1", name=INJECTION)
    assert store.get_camera("cam-3") == camera("cam-3", INJECTION)
    saved = store.get_saved_clip("saved-3")
    assert saved is not None and saved.note == INJECTION and saved.clip.label == INJECTION
    first = store.get_saved_clip("saved-1")
    assert first is not None and first.note == "'; DELETE FROM saved_clips; --"
    # Hostile ids are refused by validation, and lookups with them simply find nothing.
    assert store.get_zone(INJECTION) is None
    assert store.delete_zone(INJECTION) is False
    assert store.list_zones(INJECTION) == []

    with raw_connection(full) as db:
        tables = {
            row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
        }
    assert tables == set(TABLES)
    assert _counts(full)["saved_clips"] == 3
    assert len(store.list_zones()) == 3
