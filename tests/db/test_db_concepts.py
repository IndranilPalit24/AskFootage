"""The "concept searched" marker: a concept searched for a recording is remembered even when
it found nothing; deleting the video or the recording clears it; a v3 database upgrades in
place and keeps its rows."""

import sqlite3
from pathlib import Path

import pytest
from db_library_helpers import CAM_1, TABLES, count_rows, raw_connection, recording, track

from askfootage.adapters.sqlite import store as store_module
from askfootage.adapters.sqlite.store import SCHEMA_VERSION, SqliteLibraryStore
from askfootage.adapters.sqlite.tracks import SqliteTrackStore
from askfootage.ports.library_store import LibraryError, MissingReferenceError

V3_SCHEMA_FILE = Path(__file__).with_name("db_schema_v3.sql")
INJECTION = "x'); DROP TABLE concepts_searched;--"


@pytest.fixture
def tracks(stocked_store: SqliteLibraryStore) -> SqliteTrackStore:
    """A track store over a library holding rec-1 and rec-2 on CAM-001."""
    stocked_store.add_recording(recording("rec-2", CAM_1))
    return SqliteTrackStore(stocked_store)


def _markers(path: Path) -> list[tuple[str, str]]:
    with raw_connection(path) as db:
        return db.execute(
            "SELECT recording_id, label FROM concepts_searched ORDER BY 1, 2"
        ).fetchall()


def _table_names(path: Path) -> set[str]:
    with raw_connection(path) as db:
        rows = db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def test_a_concept_never_searched_is_not_done(tracks: SqliteTrackStore) -> None:
    assert tracks.concept_done("rec-1", "person") is False
    assert tracks.concept_done("no-such-video", "person") is False


def test_the_marker_survives_an_empty_save(tracks: SqliteTrackStore, library_path: Path) -> None:
    tracks.save_tracks("rec-1", "car", [])

    assert tracks.concept_done("rec-1", "car") is True
    assert tracks.tracks_for("rec-1", "car") == []
    assert tracks.concept_done("rec-1", "person") is False
    assert tracks.concept_done("rec-2", "car") is False
    assert _markers(library_path) == [("rec-1", "car")]
    # A reopened store still knows.
    assert SqliteTrackStore(SqliteLibraryStore(library_path)).concept_done("rec-1", "car")


def test_saving_tracks_marks_the_concept_once_and_clearing_keeps_the_marker(
    tracks: SqliteTrackStore, library_path: Path
) -> None:
    tracks.save_tracks("rec-1", "person", [track(1)])
    tracks.save_tracks("rec-1", "person", [track(2)])
    assert tracks.concept_done("rec-1", "person") is True
    assert _markers(library_path) == [("rec-1", "person")]

    tracks.save_tracks("rec-1", "person", [])
    assert tracks.tracks_for("rec-1", "person") == []
    assert tracks.concept_done("rec-1", "person") is True


def test_a_concept_with_tracks_but_no_marker_counts_as_done(
    tracks: SqliteTrackStore, library_path: Path
) -> None:
    """Tracks saved before markers existed have no marker row."""
    tracks.save_tracks("rec-1", "person", [track(1)])
    with raw_connection(library_path) as db:
        db.execute("DELETE FROM concepts_searched")

    assert tracks.concept_done("rec-1", "person") is True


def test_a_failed_save_leaves_no_marker(tracks: SqliteTrackStore, library_path: Path) -> None:
    with pytest.raises(ValueError, match="label"):
        tracks.save_tracks("rec-1", "car", [track(1, "person")])
    with pytest.raises(MissingReferenceError):
        tracks.save_tracks("no-such-video", "car", [])
    with pytest.raises(LibraryError):  # a label the schema refuses, even with no tracks
        tracks.save_tracks("rec-1", " car ", [])

    assert _markers(library_path) == []
    assert tracks.concept_done("rec-1", "car") is False


def test_delete_video_clears_its_markers_only(tracks: SqliteTrackStore, library_path: Path) -> None:
    tracks.save_tracks("rec-1", "person", [track(1)])
    tracks.save_tracks("rec-1", "car", [])
    tracks.save_tracks("rec-2", "car", [])

    assert tracks.delete_video("rec-1") == 1

    assert tracks.concept_done("rec-1", "car") is False
    assert tracks.concept_done("rec-1", "person") is False
    assert tracks.concept_done("rec-2", "car") is True
    assert _markers(library_path) == [("rec-2", "car")]


def test_delete_video_with_only_markers_removes_them(
    tracks: SqliteTrackStore, library_path: Path
) -> None:
    tracks.save_tracks("rec-1", "car", [])
    assert tracks.delete_video("rec-1") == 0
    assert _markers(library_path) == []


def test_deleting_the_recording_or_its_camera_cascades_to_the_markers(
    tracks: SqliteTrackStore, library_path: Path
) -> None:
    tracks.save_tracks("rec-1", "car", [])
    tracks.save_tracks("rec-2", "car", [])
    with raw_connection(library_path) as db:
        db.execute("DELETE FROM recordings WHERE id = 'rec-1'")
    assert _markers(library_path) == [("rec-2", "car")]

    assert tracks._library.delete_camera(CAM_1) is True
    assert _markers(library_path) == []


@pytest.mark.parametrize("label", ["", " car", "car ", "x" * 41, "\tcar"])
def test_the_schema_refuses_a_bad_marker_label(
    tracks: SqliteTrackStore, library_path: Path, label: str
) -> None:
    with raw_connection(library_path) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO concepts_searched VALUES ('rec-1', ?)", (label,))


def test_the_schema_refuses_a_repeat_and_an_unknown_recording(
    tracks: SqliteTrackStore, library_path: Path
) -> None:
    with raw_connection(library_path) as db:
        db.execute("INSERT INTO concepts_searched VALUES ('rec-1', 'xy')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO concepts_searched VALUES ('rec-1', 'xy')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO concepts_searched VALUES ('nope', 'xy')")
        db.execute("INSERT INTO concepts_searched VALUES ('rec-1', ?)", ("x" * 40,))


def test_hostile_concept_text_is_stored_as_plain_text(
    tracks: SqliteTrackStore, library_path: Path
) -> None:
    tracks.save_tracks("rec-1", INJECTION, [])

    assert tracks.concept_done("rec-1", INJECTION) is True
    assert tracks.concept_done("rec-1", "x") is False
    assert _markers(library_path) == [("rec-1", INJECTION)]
    assert count_rows(library_path, "tracks") == 0


def test_the_marker_table_is_strict_and_without_rowid(library_path: Path) -> None:
    SqliteLibraryStore(library_path)
    assert "concepts_searched" in TABLES
    with raw_connection(library_path) as db:
        row = db.execute(
            "SELECT strict, wr FROM pragma_table_list WHERE name = 'concepts_searched'"
        ).fetchone()
    assert row == (1, 1)


# --- Upgrading a real version 3 database ----------------------------------------------


def _make_v3_library(path: Path) -> None:
    """A real version 3 library (the frozen v3 schema) holding rows, tracks included."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with raw_connection(path) as db:
        db.executescript(V3_SCHEMA_FILE.read_text("utf-8"))
        db.execute(
            "INSERT INTO cameras (id, number, name, ip, username, status, created_at) "
            "VALUES ('CAM-001', 1, 'Front gate', '10.0.0.1', 'viewer', 'online', "
            "'2026-10-01T00:00:00.000000Z')"
        )
        db.execute(
            "INSERT INTO recordings (id, camera_id, day, start_time, length_seconds, status) "
            "VALUES ('rec-1', 'CAM-001', '2026-10-29', 36000, 60, 'ready')"
        )
        db.execute(
            "INSERT INTO tracks (id, recording_id, label, track_id) "
            "VALUES (7, 'rec-1', 'person', 1)"
        )
        db.execute("INSERT INTO track_points VALUES (7, 0, 1.5, 2.5, 3.5, 4.5)")


def _objects(path: Path) -> list[tuple[str, str]]:
    with raw_connection(path) as db:
        return sorted((r[0], r[1]) for r in db.execute("SELECT type, name FROM sqlite_schema"))


def test_the_v3_fixture_is_a_real_v3_library(library_path: Path) -> None:
    _make_v3_library(library_path)
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
    assert "concepts_searched" not in _table_names(library_path)


def test_a_v3_library_is_upgraded_in_place_and_keeps_its_rows(
    library_path: Path, tmp_path: Path
) -> None:
    _make_v3_library(library_path)

    store = SqliteLibraryStore(library_path)

    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 4
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert [c.id for c in store.list_cameras()] == ["CAM-001"]
    assert store.get_recording("rec-1") is not None
    assert count_rows(library_path, "track_points") == 1
    assert count_rows(library_path, "concepts_searched") == 0
    tracks = SqliteTrackStore(store)
    assert [t.track_id for t in tracks.tracks_for("rec-1", "person")] == [1]
    assert tracks.concept_done("rec-1", "person") is True  # has tracks, no marker yet
    assert tracks.concept_done("rec-1", "car") is False
    tracks.save_tracks("rec-1", "car", [])
    assert tracks.concept_done("rec-1", "car") is True
    # The same tables, indexes and triggers a brand-new library gets.
    fresh = tmp_path / "fresh" / "index.sqlite"
    SqliteLibraryStore(fresh)
    assert _objects(library_path) == _objects(fresh)


def test_opening_a_v4_file_twice_is_fine(library_path: Path) -> None:
    _make_v3_library(library_path)
    SqliteLibraryStore(library_path)
    again = SqliteLibraryStore(library_path)
    SqliteTrackStore(again).save_tracks("rec-1", "car", [])

    third = SqliteLibraryStore(library_path)

    assert SqliteTrackStore(third).concept_done("rec-1", "car") is True
    assert count_rows(library_path, "track_points") == 1


def test_a_failed_v3_upgrade_leaves_the_v3_library_as_it_was(
    library_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_v3_library(library_path)
    broken = store_module._MIGRATIONS[3] + "\nCREATE TABLE (;"
    monkeypatch.setitem(store_module._MIGRATIONS, 3, broken)

    with pytest.raises(LibraryError, match="could not be opened"):
        SqliteLibraryStore(library_path)

    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
    assert "concepts_searched" not in _table_names(library_path)
    assert count_rows(library_path, "track_points") == 1
    monkeypatch.undo()
    SqliteLibraryStore(library_path)
    assert count_rows(library_path, "concepts_searched") == 0
