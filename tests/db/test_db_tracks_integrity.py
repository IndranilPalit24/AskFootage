"""Tracks at the schema level: cascades from recordings and cameras, constraints that refuse
bad rows from any writer, the indexes the common queries use, and bulk-write speed."""

import re
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from db_library_helpers import (
    CAM_1,
    CAM_2,
    count_rows,
    new_camera,
    raw_connection,
    recording,
    track,
)

from askfootage.adapters.sqlite import tracks as tracks_module
from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.adapters.sqlite.tracks import SqliteTrackStore
from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint


@pytest.fixture
def two_cameras(store: SqliteLibraryStore) -> SqliteTrackStore:
    """CAM-001 with rec-1 and rec-2, CAM-002 with rec-3; each recording has two person
    tracks of three points and one box track of one point."""
    store.add_camera(new_camera("Front gate"))
    store.add_camera(new_camera("Yard"))
    store.add_recording(recording("rec-1", CAM_1))
    store.add_recording(recording("rec-2", CAM_1))
    store.add_recording(recording("rec-3", CAM_2))
    tracks = SqliteTrackStore(store)
    for recording_id in ("rec-1", "rec-2", "rec-3"):
        tracks.save_tracks(recording_id, "person", [track(1), track(2)])
        tracks.save_tracks(recording_id, "box", [track(1, "box", frames=(4,))])
    return tracks


def _counts(path: Path) -> tuple[int, int]:
    return count_rows(path, "tracks"), count_rows(path, "track_points")


def _assert_no_orphans(path: Path) -> None:
    with raw_connection(path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


# --- Cascades --------------------------------------------------------------------------


def test_deleting_a_recording_row_removes_its_tracks_and_points(
    two_cameras: SqliteTrackStore, library_path: Path
) -> None:
    assert _counts(library_path) == (9, 21)
    with raw_connection(library_path) as db:
        db.execute("DELETE FROM recordings WHERE id = ?", ("rec-1",))

    assert _counts(library_path) == (6, 14)
    _assert_no_orphans(library_path)
    assert two_cameras.tracks_for("rec-1", "person") == []
    assert two_cameras.tracks_for("rec-2", "person") == [track(1), track(2)]


def test_delete_camera_removes_the_tracks_of_its_recordings_only(
    two_cameras: SqliteTrackStore, store: SqliteLibraryStore, library_path: Path
) -> None:
    assert store.delete_camera(CAM_1) is True

    assert _counts(library_path) == (3, 7)
    _assert_no_orphans(library_path)
    assert two_cameras.tracks_for("rec-1", "person") == []
    assert two_cameras.tracks_for("rec-2", "box") == []
    assert two_cameras.tracks_for("rec-3", "person") == [track(1), track(2)]
    assert two_cameras.tracks_for("rec-3", "box") == [track(1, "box", frames=(4,))]


def test_deleting_a_track_row_removes_its_points(
    two_cameras: SqliteTrackStore, library_path: Path
) -> None:
    with raw_connection(library_path) as db:
        db.execute("DELETE FROM tracks WHERE recording_id = 'rec-3' AND label = 'box'")
    assert _counts(library_path) == (8, 20)
    _assert_no_orphans(library_path)


# --- Constraints, written past the store with raw SQL -----------------------------------


@pytest.fixture
def db(two_cameras: SqliteTrackStore, library_path: Path) -> Iterator[sqlite3.Connection]:
    """A raw connection (foreign keys on) to a library holding rec-1, rec-2 and rec-3."""
    with raw_connection(library_path) as connection:
        yield connection


def _a_track_row(db: sqlite3.Connection) -> int:
    return db.execute(
        "SELECT id FROM tracks WHERE recording_id = 'rec-1' AND label = 'person' AND track_id = 1"
    ).fetchone()[0]


_GOOD_TRACK = {"recording_id": "rec-1", "label": "cardboard box", "track_id": 5}


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("recording_id", "rec-nope"),
        ("recording_id", None),
        ("label", ""),
        ("label", "   "),
        ("label", " person"),
        ("label", "person\n"),
        ("label", "x" * 41),
        ("label", None),
        ("label", b"person"),  # a BLOB is not text
        ("track_id", -1),
        ("track_id", None),
        ("track_id", 1.5),
        ("track_id", "one"),
    ],
)
def test_the_schema_refuses_a_bad_track_row(
    db: sqlite3.Connection, column: str, value: object
) -> None:
    row = {**_GOOD_TRACK, column: value}
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO tracks (recording_id, label, track_id) VALUES (?, ?, ?)",
            (row["recording_id"], row["label"], row["track_id"]),
        )


def test_the_schema_accepts_a_good_track_row_at_the_edges(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO tracks (recording_id, label, track_id) VALUES ('rec-1', ?, 0)", ("x" * 40,)
    )


def test_the_schema_refuses_a_repeated_track_id_for_one_video_and_label(
    db: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        db.execute(
            "INSERT INTO tracks (recording_id, label, track_id) VALUES ('rec-1', 'person', 1)"
        )
    # The same id under another label or video is a different track.
    db.execute("INSERT INTO tracks (recording_id, label, track_id) VALUES ('rec-1', 'cat', 1)")


_GOOD_POINT = {"frame": 3, "x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0}


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("frame", -1),
        ("frame", None),
        ("frame", 2.5),
        ("x1", 3.5),  # x1 > x2
        ("y1", 4.5),  # y1 > y2
        ("x2", 0.5),  # x2 < x1
        ("y2", 1.5),  # y2 < y1
        ("x1", float("-inf")),
        ("x2", float("inf")),
        ("y1", float("-inf")),
        ("y2", float("inf")),
        ("x1", float("nan")),  # SQLite turns NaN into NULL
        ("y2", None),
        ("x1", "left"),
    ],
)
def test_the_schema_refuses_a_bad_point_row(
    db: sqlite3.Connection, column: str, value: object
) -> None:
    row = {**_GOOD_POINT, column: value}
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO track_points (track_row, frame, x1, y1, x2, y2) VALUES (?, ?, ?, ?, ?, ?)",
            (_a_track_row(db), row["frame"], row["x1"], row["y1"], row["x2"], row["y2"]),
        )


def test_the_schema_accepts_a_point_at_the_edges(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO track_points (track_row, frame, x1, y1, x2, y2) VALUES (?, 99, ?, ?, ?, ?)",
        (_a_track_row(db), -1.7976931348623157e308, 5.0, 1.7976931348623157e308, 5.0),
    )


def test_the_schema_refuses_a_repeated_frame_and_a_point_without_a_track(
    db: sqlite3.Connection,
) -> None:
    track_row = _a_track_row(db)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        db.execute(
            "INSERT INTO track_points (track_row, frame, x1, y1, x2, y2) VALUES (?, 0, 1, 1, 2, 2)",
            (track_row,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute(
            "INSERT INTO track_points (track_row, frame, x1, y1, x2, y2) "
            "VALUES (999999, 0, 1, 1, 2, 2)"
        )


# --- Indexes ---------------------------------------------------------------------------

_FULL_SCAN = re.compile(r"\bSCAN (tracks|track_points|t|p)\b(?! USING)")


def _plan(path: Path, sql: str, params: tuple[object, ...]) -> str:
    with raw_connection(path) as db:
        return " | ".join(row[3] for row in db.execute(f"EXPLAIN QUERY PLAN {sql}", params))


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        (tracks_module._POINTS_OF_TRACKS, ("rec-1", "person")),
        (tracks_module._DELETE_CONCEPT, ("rec-1", "person")),
        (tracks_module._DELETE_VIDEO, ("rec-1",)),
    ],
    ids=["tracks_for", "replace", "delete_video"],
)
def test_track_queries_seek_an_index_and_need_no_sort(
    library_path: Path, store: SqliteLibraryStore, sql: str, params: tuple[object, ...]
) -> None:
    plan = _plan(library_path, sql, params)
    assert "INDEX" in plan, plan
    assert "TEMP B-TREE" not in plan, plan
    assert not _FULL_SCAN.search(plan), plan


def test_tracks_for_walks_the_video_and_label_index_then_each_tracks_points(
    library_path: Path, store: SqliteLibraryStore
) -> None:
    plan = _plan(library_path, tracks_module._POINTS_OF_TRACKS, ("rec-1", "person"))
    assert re.search(r"SEARCH t USING (COVERING )?INDEX \w+ \(recording_id=\? AND label=\?\)", plan)
    assert re.search(r"SEARCH p USING PRIMARY KEY \(track_row=\?\)", plan), plan


# --- Bulk writes -----------------------------------------------------------------------

FIVE_THOUSAND = 5_000


def _long_track(track_id: int, points: int) -> Track:
    return Track(
        track_id=track_id,
        label="person",
        points=tuple(
            TrackPoint(frame * 2, BoundingBox(frame * 0.5, 1.25, frame * 0.5 + 40.125, 99.5))
            for frame in range(points)
        ),
    )


def test_a_track_of_five_thousand_points_saves_and_loads_well_under_a_second(
    two_cameras: SqliteTrackStore, library_path: Path
) -> None:
    long = _long_track(42, FIVE_THOUSAND)

    started = time.perf_counter()
    two_cameras.save_tracks("rec-1", "person", [long])
    saved_in = time.perf_counter() - started
    started = time.perf_counter()
    found = two_cameras.tracks_for("rec-1", "person")
    loaded_in = time.perf_counter() - started

    print(f"5,000 points: saved in {saved_in * 1000:.1f} ms, loaded in {loaded_in * 1000:.1f} ms")
    assert found == [long]
    assert saved_in < 1.0, saved_in
    assert loaded_in < 1.0, loaded_in
    assert count_rows(library_path, "track_points") == 21 - 6 + FIVE_THOUSAND


def test_replacing_many_long_tracks_stays_fast(two_cameras: SqliteTrackStore) -> None:
    """Twenty tracks of 5,000 points (100,000 rows) replaced by another twenty."""
    first = [_long_track(i, FIVE_THOUSAND) for i in range(20)]
    second = [_long_track(i + 100, FIVE_THOUSAND) for i in range(20)]
    two_cameras.save_tracks("rec-1", "person", first)

    started = time.perf_counter()
    two_cameras.save_tracks("rec-1", "person", second)
    elapsed = time.perf_counter() - started

    print(f"100,000 points replaced in {elapsed * 1000:.1f} ms")
    assert elapsed < 5.0, elapsed
    assert [t.track_id for t in two_cameras.tracks_for("rec-1", "person")] == list(range(100, 120))
