"""The schema itself refuses bad rows: every CHECK, FOREIGN KEY, UNIQUE and NOT NULL.

These tests write raw SQL, past the dataclasses and the store, because the database must
stay sound even when something other than the store writes to it. Each bad row is a known
good row with one value changed, so a failure can only come from that value.
"""

import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest
from db_library_helpers import (
    CAM_1,
    CAM_2,
    clip,
    new_camera,
    raw_connection,
    recording,
    stored_camera,
    zone,
)

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.ports.library_store import (
    Evidence,
    KeyFrame,
    LibraryError,
    Recording,
    SavedClip,
    Zone,
)

INSERTS = {
    "cameras": (
        "INSERT INTO cameras (id, number, name, ip, username, status, location, department, "
        "created_at) VALUES (:id, :number, :name, :ip, :username, :status, :location, "
        ":department, :created_at)"
    ),
    "recordings": (
        "INSERT INTO recordings (id, camera_id, day, start_time, length_seconds, status) "
        "VALUES (:id, :camera_id, :day, :start_time, :length_seconds, :status)"
    ),
    "clips": (
        "INSERT INTO clips (id, recording_id, camera_id, day, start_time, start_seconds, "
        "end_seconds, label, zone, why_matched, thumbnail_url) VALUES (:id, :recording_id, "
        ":camera_id, :day, :start_time, :start_seconds, :end_seconds, :label, :zone, "
        ":why_matched, :thumbnail_url)"
    ),
    "clip_evidence": (
        "INSERT INTO clip_evidence (clip_id, position, kind, text) "
        "VALUES (:clip_id, :position, :kind, :text)"
    ),
    "clip_key_frames": (
        "INSERT INTO clip_key_frames (clip_id, position, at_seconds, image_url) "
        "VALUES (:clip_id, :position, :at_seconds, :image_url)"
    ),
    "zones": "INSERT INTO zones (id, camera_id, name) VALUES (:id, :camera_id, :name)",
    "zone_points": (
        "INSERT INTO zone_points (zone_id, position, x, y) VALUES (:zone_id, :position, :x, :y)"
    ),
    "saved_clips": (
        "INSERT INTO saved_clips (id, clip_id, note, saved_at) "
        "VALUES (:id, :clip_id, :note, :saved_at)"
    ),
}

# One valid new row per table, given the rows the `base` fixture stores.
GOOD = {
    # CAM-001 and CAM-002 are taken, so the next number is 3.
    "cameras": {
        "id": "CAM-003",
        "number": 3,
        "name": "Back door",
        "ip": "cam-backdoor.local",
        "username": "admin",
        "status": "offline",
        "location": "x" * 80,
        "department": None,
        "created_at": "2026-10-30T09:00:00.000000Z",
    },
    "recordings": {
        "id": "rec-new",
        "camera_id": CAM_1,
        "day": "2026-10-30",
        "start_time": 0,
        "length_seconds": 0,
        "status": "waiting",
    },
    "clips": {
        "id": "clip-new",
        "recording_id": "rec-1",
        "camera_id": CAM_1,
        "day": "2026-10-29",
        "start_time": 86399,
        "start_seconds": 0,
        "end_seconds": 1,
        "label": "Person",
        "zone": None,
        "why_matched": "",
        "thumbnail_url": None,
    },
    "clip_evidence": {"clip_id": "clip-1", "position": 9, "kind": "dwell", "text": "Stayed"},
    "clip_key_frames": {"clip_id": "clip-1", "position": 9, "at_seconds": 0, "image_url": None},
    "zones": {"id": "zone-new", "camera_id": CAM_1, "name": "x" * 60},
    "zone_points": {"zone_id": "zone-1", "position": 9, "x": 0.0, "y": 1.0},
    "saved_clips": {
        "id": "saved-new",
        "clip_id": "clip-2",
        "note": "x" * 500,
        "saved_at": "2026-10-30T09:12:44.000000Z",
    },
}

INJECTION = "x'); DROP TABLE zones;--"

BAD = [
    # cameras
    ("cameras", "id", ""),
    ("cameras", "id", "x" * 65),
    ("cameras", "id", "bad id"),
    ("cameras", "id", "café"),
    ("cameras", "id", INJECTION),
    ("cameras", "id", None),
    ("cameras", "id", CAM_1),  # taken (and not number 3's id)
    ("cameras", "id", "CAM-3"),  # one spelling per number: CAM-003
    ("cameras", "id", "CAM-0003"),
    ("cameras", "id", "cam-003"),
    ("cameras", "number", 2),  # taken, and already handed out
    ("cameras", "number", 0),
    ("cameras", "number", None),
    ("cameras", "number", 3.5),
    ("cameras", "name", ""),
    ("cameras", "name", " \t\n "),
    ("cameras", "name", None),
    ("cameras", "name", b"bytes"),
    ("cameras", "name", "x" * 81),
    ("cameras", "name", "FRONT GATE"),  # CAM-001's name in another case
    ("cameras", "ip", ""),
    ("cameras", "ip", "  "),
    ("cameras", "ip", "a" * 254),
    ("cameras", "ip", None),
    ("cameras", "username", ""),
    ("cameras", "username", "x" * 65),
    ("cameras", "username", None),
    ("cameras", "status", "deleted"),
    ("cameras", "status", "ONLINE"),
    ("cameras", "status", None),
    ("cameras", "location", ""),
    ("cameras", "location", " "),
    ("cameras", "location", "x" * 81),
    ("cameras", "department", ""),
    ("cameras", "department", "x" * 81),
    ("cameras", "created_at", "2026-10-30T09:00:00Z"),
    ("cameras", "created_at", "2026-10-30T09:00:00.000000+00:00"),
    ("cameras", "created_at", "2026-02-30T09:00:00.000000Z"),
    ("cameras", "created_at", None),
    # recordings
    ("recordings", "id", "rec-1"),  # taken
    ("recordings", "id", "rec 2"),
    ("recordings", "camera_id", "no-such-camera"),
    ("recordings", "camera_id", None),
    ("recordings", "day", "2026-1-05"),
    ("recordings", "day", "2026-02-30"),
    ("recordings", "day", "2026-13-01"),
    ("recordings", "day", "2026-10-30T00:00:00"),
    ("recordings", "day", "tomorrow"),
    ("recordings", "day", ""),
    ("recordings", "start_time", -1),
    ("recordings", "start_time", 86400),
    ("recordings", "start_time", "10:00:00"),
    ("recordings", "start_time", 3.5),
    ("recordings", "start_time", None),
    ("recordings", "length_seconds", -1),
    ("recordings", "status", "done"),
    ("recordings", "status", "READY"),
    ("recordings", "status", None),
    # clips
    ("clips", "id", "clip-1"),  # taken
    ("clips", "recording_id", "no-such-recording"),
    ("clips", "day", "2026-10-30"),  # not rec-1's day
    ("clips", "camera_id", CAM_2),  # not rec-1's camera
    ("clips", "start_time", -1),
    ("clips", "start_time", 86400),
    ("clips", "start_seconds", -1),
    ("clips", "end_seconds", 0),  # == start_seconds
    ("clips", "end_seconds", -5),
    ("clips", "label", "  "),
    ("clips", "label", None),
    ("clips", "why_matched", None),
    # clip_evidence
    ("clip_evidence", "clip_id", "no-such-clip"),
    ("clip_evidence", "position", -1),
    ("clip_evidence", "position", 0),  # taken
    ("clip_evidence", "kind", "face"),
    ("clip_evidence", "kind", "person"),
    ("clip_evidence", "kind", None),
    ("clip_evidence", "text", " "),
    # clip_key_frames
    ("clip_key_frames", "clip_id", "no-such-clip"),
    ("clip_key_frames", "position", 0),  # taken
    ("clip_key_frames", "position", -1),
    ("clip_key_frames", "at_seconds", -1),
    ("clip_key_frames", "at_seconds", None),
    # zones
    ("zones", "id", "zone-1"),  # taken
    ("zones", "camera_id", "no-such-camera"),
    ("zones", "name", "Gate"),  # CAM-001 already has a zone named Gate
    ("zones", "name", ""),
    ("zones", "name", "   "),
    ("zones", "name", "x" * 61),
    ("zones", "name", None),
    # zone_points
    ("zone_points", "zone_id", "no-such-zone"),
    ("zone_points", "position", 0),  # taken
    ("zone_points", "position", -1),
    ("zone_points", "x", -0.01),
    ("zone_points", "x", 1.01),
    ("zone_points", "y", 2),
    ("zone_points", "y", -1),
    ("zone_points", "x", None),
    ("zone_points", "y", float("nan")),
    ("zone_points", "x", float("inf")),
    # saved_clips
    ("saved_clips", "id", "saved-1"),  # taken
    ("saved_clips", "clip_id", "no-such-clip"),
    ("saved_clips", "clip_id", "clip-1"),  # already saved
    ("saved_clips", "note", "x" * 501),
    ("saved_clips", "note", None),
    ("saved_clips", "saved_at", "2026-10-30 09:12:44.000000Z"),
    ("saved_clips", "saved_at", "2026-10-30T09:12:44Z"),
    ("saved_clips", "saved_at", "2026-10-30T09:12:44.000000+00:00"),
    ("saved_clips", "saved_at", "2026-10-30T25:00:00.000000Z"),
    ("saved_clips", "saved_at", "2026-10-30T09:60:00.000000Z"),
    ("saved_clips", "saved_at", "2026-02-30T09:00:00.000000Z"),
    ("saved_clips", "saved_at", "yesterday"),
]


@pytest.fixture
def base(stocked_store: SqliteLibraryStore, library_path: Path) -> Path:
    """CAM-001 "Front gate" and CAM-002 "Yard"; rec-1 on CAM-001, 29 Oct; clip-1 (saved as
    saved-1) and clip-2; zone-1 "Gate" on CAM-001."""
    assert stocked_store.add_camera(new_camera("Yard")).id == CAM_2
    stocked_store.add_clip(clip("clip-2", start_time=time(10, 1), start_seconds=60, end_seconds=70))
    stocked_store.add_zone(zone())
    stocked_store.add_saved_clip("saved-1", "clip-1", "", datetime(2026, 10, 30, 9, tzinfo=UTC))
    return library_path


@pytest.mark.parametrize("table", sorted(GOOD))
def test_each_good_row_is_accepted(base: Path, table: str) -> None:
    with raw_connection(base) as db:
        db.execute(INSERTS[table], GOOD[table])


@pytest.mark.parametrize(
    ("table", "column", "value"),
    BAD,
    ids=[f"{table}.{column}={value!r:.24}" for table, column, value in BAD],
)
def test_each_bad_value_is_refused(base: Path, table: str, column: str, value: object) -> None:
    row = {**GOOD[table], column: value}
    with raw_connection(base) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute(INSERTS[table], row)


def test_the_same_zone_name_is_fine_on_another_camera(base: Path) -> None:
    with raw_connection(base) as db:
        db.execute(INSERTS["zones"], {"id": "zone-2", "camera_id": CAM_2, "name": "Gate"})


def test_a_recordings_camera_or_day_cannot_change_under_its_clips(base: Path) -> None:
    with raw_connection(base) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE recordings SET day = '2026-10-30' WHERE id = 'rec-1'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE recordings SET camera_id = ? WHERE id = 'rec-1'", (CAM_2,))


def test_an_update_cannot_break_a_check_either(base: Path) -> None:
    with raw_connection(base) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE clips SET end_seconds = start_seconds WHERE id = 'clip-1'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE zone_points SET x = 1.5 WHERE zone_id = 'zone-1'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE saved_clips SET note = ? WHERE id = 'saved-1'", ("x" * 501,))


def test_the_camera_triggers_keep_numbers_unique_forever(base: Path) -> None:
    """A deleted camera's number cannot come back, and the sequence only counts up."""
    reused = {**GOOD["cameras"], "id": CAM_2, "number": 2}
    with raw_connection(base) as db:
        db.execute("DELETE FROM cameras WHERE id = ?", (CAM_2,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(INSERTS["cameras"], reused)  # CAM-002 was handed out already
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE camera_sequence SET last_number = 1")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM camera_sequence")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO camera_sequence (only_row, last_number) VALUES (2, 9)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE cameras SET id = 'CAM-009', number = 9 WHERE id = ?", (CAM_1,))
        db.execute(INSERTS["cameras"], GOOD["cameras"])  # CAM-003 moves the sequence on
        assert db.execute("SELECT last_number FROM camera_sequence").fetchone()[0] == 3


# --- The other layer: the store refuses what the dataclasses let through ------------


def test_store_refuses_a_zone_name_over_60_characters(base: Path) -> None:
    store = SqliteLibraryStore(base)
    with pytest.raises(LibraryError, match="60"):
        store.add_zone(zone("zone-2", name="x" * 61))
    with pytest.raises(LibraryError, match="60"):
        store.replace_zone(zone("zone-1", name="x" * 61))
    assert store.get_zone("zone-1") == zone()


def test_store_refuses_a_note_over_500_characters(base: Path) -> None:
    store = SqliteLibraryStore(base)
    with pytest.raises(LibraryError, match="500"):
        store.add_saved_clip("saved-2", "clip-2", "x" * 501, datetime.now().astimezone())
    with pytest.raises(LibraryError, match="500"):
        store.update_note("saved-1", "x" * 501)
    assert store.get_saved_clip("saved-2") is None


@pytest.mark.parametrize(
    "start_time",
    [time(10, 0, 0, 500_000), time(10, 0, 0, tzinfo=datetime.now().astimezone().tzinfo)],
    ids=["microseconds", "time-zone"],
)
def test_store_refuses_a_time_it_cannot_hold_exactly(base: Path, start_time: time) -> None:
    store = SqliteLibraryStore(base)
    with pytest.raises(LibraryError, match="whole seconds"):
        store.add_recording(recording("rec-2", start_time=start_time))
    with pytest.raises(LibraryError, match="whole seconds"):
        store.add_clip(clip("clip-3", start_time=start_time))
    assert store.get_recording("rec-2") is None
    assert store.get_clip("clip-3") is None


def test_store_refuses_a_datetime_where_a_day_belongs(base: Path) -> None:
    store = SqliteLibraryStore(base)
    with pytest.raises(TypeError):
        store.add_recording(recording("rec-2", day=datetime(2026, 10, 29, 12)))
    with pytest.raises(TypeError):
        store.list_recordings(CAM_1, datetime(2026, 10, 29, 12))


def test_store_refuses_a_number_too_large_for_sqlite(base: Path) -> None:
    store = SqliteLibraryStore(base)
    with pytest.raises(LibraryError, match="too large"):
        store.add_recording(recording("rec-2", length_seconds=2**64))
    assert store.get_recording("rec-2") is None


@pytest.mark.parametrize(
    "build",
    [
        lambda: stored_camera("bad id", new_camera()),
        lambda: stored_camera("CAM-1", new_camera()),
        lambda: new_camera("  "),
        lambda: Recording("rec-9", CAM_1, date(2026, 10, 29), time(1), -1, "ready"),
        lambda: Recording("rec-9", CAM_1, date(2026, 10, 29), time(1), 1, "done"),
        lambda: Evidence("face", "Face"),
        lambda: Evidence("dwell", " "),
        lambda: KeyFrame(-1),
        lambda: clip("clip-9", start_seconds=5, end_seconds=5),
        lambda: clip("clip-9", label=" "),
        lambda: Zone("zone-9", CAM_1, "Gate", ((0, 0), (1, 0))),
        lambda: Zone("zone-9", CAM_1, "Gate", ((0, 0), (1, 0), (1, 1.5))),
        lambda: Zone("zone-9", CAM_1, " ", ((0, 0), (1, 0), (1, 1))),
        lambda: SavedClip("saved-9", clip(), "", datetime(2026, 10, 30)),
    ],
    ids=[
        "camera-id",
        "camera-id-unpadded",
        "camera-name",
        "recording-length",
        "recording-status",
        "evidence-kind",
        "evidence-text",
        "key-frame",
        "clip-range",
        "clip-label",
        "zone-two-points",
        "zone-point-range",
        "zone-name",
        "saved-naive-time",
    ],
)
def test_the_dataclasses_refuse_bad_values_before_any_sql(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        build()


def test_a_zone_slipping_past_its_dataclass_with_two_points_is_rolled_back(base: Path) -> None:
    store = SqliteLibraryStore(base)
    sneaky = zone("zone-2", name="Sneaky")
    object.__setattr__(sneaky, "points", ((0.1, 0.1), (0.9, 0.9)))
    sneaky_replacement = zone("zone-1", name="Renamed")
    object.__setattr__(sneaky_replacement, "points", ((0.1, 0.1), (0.9, 0.9)))

    with pytest.raises(LibraryError, match="at least 3 points"):
        store.add_zone(sneaky)
    with pytest.raises(LibraryError, match="at least 3 points"):
        store.replace_zone(sneaky_replacement)

    assert store.get_zone("zone-2") is None
    assert store.get_zone("zone-1") == zone()  # name and points as before


def test_a_clip_slipping_past_its_dataclass_is_rolled_back_whole(base: Path) -> None:
    store = SqliteLibraryStore(base)
    sneaky = clip("clip-3", evidence=(Evidence("dwell", "Stayed"), Evidence("dwell", "Again")))
    object.__setattr__(sneaky.evidence[1], "kind", "face")

    with pytest.raises(LibraryError) as refused:
        store.add_clip(sneaky)

    assert "CHECK" not in str(refused.value)
    assert store.get_clip("clip-3") is None
    with raw_connection(base) as db:
        rows = db.execute("SELECT count(*) FROM clip_evidence WHERE clip_id = 'clip-3'")
        assert rows.fetchone()[0] == 0
