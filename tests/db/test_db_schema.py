"""Creating, reopening, upgrading and refusing library databases; the schema's version,
indexes, and the columns it must never have (identity, passwords).

Older versions held demo data only, so opening a v1 or v2 library drops it and creates the
current schema; the demo seed then refills it."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from db_library_helpers import (
    CAM_1,
    DEMO_SEED,
    TABLES,
    count_rows,
    new_camera,
    raw_connection,
    recording,
    stored_camera,
)

from askfootage.adapters.sqlite import store as store_module
from askfootage.adapters.sqlite.store import SCHEMA_VERSION, SqliteLibraryStore, seed_demo_data
from askfootage.ports.library_store import LibraryError

SCHEMA_FILE = Path(store_module.__file__).with_name("schema.sql")
V1_SCHEMA_FILE = Path(__file__).with_name("db_schema_v1.sql")
V2_SCHEMA_FILE = Path(__file__).with_name("db_schema_v2.sql")
V1_TABLES = {
    "cameras",
    "recordings",
    "clips",
    "clip_evidence",
    "clip_key_frames",
    "zones",
    "zone_points",
    "saved_clips",
}


def _table_names(path: Path) -> set[str]:
    with raw_connection(path) as db:
        rows = db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def test_a_new_library_gets_every_table_and_the_schema_version(library_path: Path) -> None:
    SqliteLibraryStore(library_path)

    assert _table_names(library_path) == set(TABLES)
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_the_version_in_schema_sql_is_the_one_the_code_expects() -> None:
    versions = re.findall(r"PRAGMA user_version = (\d+);", SCHEMA_FILE.read_text("utf-8"))
    assert versions == [str(SCHEMA_VERSION)]


def test_every_table_is_strict(library_path: Path) -> None:
    SqliteLibraryStore(library_path)
    with raw_connection(library_path) as db:
        rows = db.execute("SELECT name, strict FROM pragma_table_list WHERE schema = 'main'")
        strict = {name: flag for name, flag in rows if not name.startswith("sqlite_")}
    assert strict == dict.fromkeys(TABLES, 1)


def test_the_parent_folder_is_created(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "library.sqlite"
    SqliteLibraryStore(path)
    assert path.is_file()


def test_opening_the_same_file_again_keeps_the_data_and_the_version(library_path: Path) -> None:
    first = SqliteLibraryStore(library_path)
    added = first.add_camera(new_camera())
    first.add_recording(recording())

    second = SqliteLibraryStore(library_path)
    third = SqliteLibraryStore(library_path)

    assert second.list_cameras() == [added] == [stored_camera(CAM_1, new_camera())]
    assert third.get_recording("rec-1") == recording()
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_a_database_with_a_newer_schema_is_refused_and_left_alone(library_path: Path) -> None:
    SqliteLibraryStore(library_path)
    with raw_connection(library_path) as db:
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    with pytest.raises(LibraryError, match="newer") as refused:
        SqliteLibraryStore(library_path)

    assert str(library_path.parent) not in str(refused.value)
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION + 1


def test_a_database_holding_other_tables_is_refused_and_left_alone(library_path: Path) -> None:
    library_path.parent.mkdir(parents=True)
    with raw_connection(library_path) as db:
        db.execute("CREATE TABLE something_else (x INTEGER)")

    with pytest.raises(LibraryError, match="did not create"):
        SqliteLibraryStore(library_path)

    assert _table_names(library_path) == {"something_else"}


def test_a_file_that_is_not_a_database_is_refused_without_naming_the_path(
    library_path: Path,
) -> None:
    library_path.parent.mkdir(parents=True)
    library_path.write_bytes(b"this is not a SQLite database, just some bytes " * 40)

    with pytest.raises(LibraryError, match="could not be opened") as refused:
        SqliteLibraryStore(library_path)

    message = str(refused.value)
    assert str(library_path.parent) not in message
    assert "sqlite3" not in message.lower()
    assert refused.value.__cause__ is None
    assert refused.value.__suppress_context__


def test_an_empty_existing_file_becomes_a_library(library_path: Path) -> None:
    library_path.parent.mkdir(parents=True)
    library_path.touch()
    SqliteLibraryStore(library_path)
    assert _table_names(library_path) == set(TABLES)


def test_an_in_memory_database_is_refused() -> None:
    with pytest.raises(ValueError, match="file path"):
        SqliteLibraryStore(Path(":memory:"))


def test_no_column_could_hold_an_identity(library_path: Path) -> None:
    """ADR 0008: nothing in the schema names, describes or identifies a person."""
    SqliteLibraryStore(library_path)
    with raw_connection(library_path) as db:
        columns = {
            row[0]
            for table in TABLES
            for row in db.execute("SELECT name FROM pragma_table_info(?)", (table,))
        }
    forbidden = ("face", "person", "identity", "embedding", "biometric", "track_name")
    assert not [column for column in columns if any(word in column for word in forbidden)]
    # The only free-text name columns are a camera's and a zone's, which name places, and a
    # camera's stream login (such as "viewer"), which names an account on the device.
    assert {column for column in columns if "name" in column} == {"name", "username"}


def _every_column(path: Path) -> dict[str, list[str]]:
    """Each table's columns, for every table in the file (not only the expected ones)."""
    with raw_connection(path) as db:
        tables = [
            row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
        ]
        return {
            table: [row[0] for row in db.execute("SELECT name FROM pragma_table_info(?)", (table,))]
            for table in tables
        }


def test_no_column_could_hold_a_password(seeded_store: SqliteLibraryStore) -> None:
    """A camera's stream password is checked by the API and dropped, never stored."""
    columns = _every_column(seeded_store.path)
    assert set(columns) == set(TABLES)
    secretive = ("pass", "pwd", "secret", "credential", "token", "auth", "key")
    found = [
        f"{table}.{column}"
        for table, names in columns.items()
        for column in names
        if any(word in column.lower() for word in secretive)
    ]
    assert found == []
    assert columns["cameras"] == [
        "id",
        "number",
        "name",
        "ip",
        "username",
        "status",
        "location",
        "department",
        "created_at",
    ]


# The common queries must be answered from an index, in index order (no sort step).
_INDEXED_QUERIES = {
    "list_cameras": (store_module._CAMERAS, ()),
    "camera_counts": (store_module._CAMERA_COUNTS, ()),
    "list_recordings": (store_module._RECORDINGS_ON_DAY, (CAM_1, "2026-10-29")),
    "list_recordings_all": (store_module._RECORDINGS_ON_DAY_ALL_CAMERAS, ("2026-10-29",)),
    "summarise_days": (store_module._DAY_SUMMARIES, (CAM_1, "2026-10-24", "2026-10-30")),
    "summarise_days_all": (
        store_module._DAY_SUMMARIES_ALL_CAMERAS,
        ("2026-10-24", "2026-10-30"),
    ),
    "list_clips": (store_module._CLIPS_ON_DAY, (CAM_1, "2026-10-29")),
    "list_clips_all": (store_module._CLIPS_ON_DAY_ALL_CAMERAS, ("2026-10-29",)),
    "all_zones": (store_module._ALL_ZONES, ()),
    "zones_of_camera": (store_module._ZONES_OF_CAMERA, (CAM_1,)),
    "other_zone_names": (store_module._OTHER_ZONE_NAMES, (CAM_1, "zone-1")),
    "saved_clips": (store_module._SAVED_CLIPS, ()),
    "saved_clips_on_day": (store_module._SAVED_CLIPS_ON_DAY, ("2026-10-29",)),
    "clip_already_saved": (store_module._CLIP_ALREADY_SAVED, ("clip-1",)),
    "evidence_of_clips": (store_module._EVIDENCE_OF_CLIPS, ('["clip-1"]',)),
    "key_frames_of_clips": (store_module._KEY_FRAMES_OF_CLIPS, ('["clip-1"]',)),
    "points_of_zones": (store_module._POINTS_OF_ZONES, ('["zone-1"]',)),
}


# A step that reads a whole table row by row, without an index.
_FULL_SCAN = re.compile(r"\bSCAN (cameras|clips|recordings|zones|c|k)\b(?! USING)")


def _plan(path: Path, query: str) -> str:
    sql, params = _INDEXED_QUERIES[query]
    with raw_connection(path) as db:
        return " | ".join(row[3] for row in db.execute(f"EXPLAIN QUERY PLAN {sql}", params))


def test_the_full_scan_pattern_catches_a_full_scan() -> None:
    """Guards the guard: this pattern once held backspace bytes and matched nothing."""
    assert _FULL_SCAN.search("SCAN recordings")
    assert _FULL_SCAN.search("MATERIALIZE r | SCAN c | SEARCH r")
    assert not _FULL_SCAN.search("SCAN recordings USING COVERING INDEX recordings_by_day")
    assert not _FULL_SCAN.search("SCAN cameras USING INDEX sqlite_autoindex_cameras_2")


@pytest.mark.parametrize("query", sorted(_INDEXED_QUERIES))
def test_common_queries_use_an_index_and_need_no_sort(library_path: Path, query: str) -> None:
    SqliteLibraryStore(library_path)
    plan = _plan(library_path, query)

    assert "USING" in plan and "INDEX" in plan, plan
    assert "TEMP B-TREE" not in plan, plan
    assert not _FULL_SCAN.search(plan), plan


@pytest.mark.parametrize(
    ("query", "index"),
    [
        ("list_recordings", "recordings_by_camera_day"),
        ("list_recordings_all", "recordings_by_day"),
        ("summarise_days", "recordings_by_camera_day"),
        ("summarise_days_all", "recordings_by_day"),
        ("list_clips", "clips_by_camera_day"),
        ("list_clips_all", "clips_by_day"),
    ],
)
def test_one_camera_and_all_camera_day_queries_each_seek_their_own_index(
    library_path: Path, query: str, index: str
) -> None:
    """Both forms seek straight to the day; the all-camera form must not fall back to
    walking the per-camera index (or the table) from its start."""
    SqliteLibraryStore(library_path)
    plan = _plan(library_path, query)
    assert re.fullmatch(rf"SEARCH \w+ USING (COVERING )?INDEX {index} \(.*day.*\)", plan), plan


def test_every_foreign_key_leads_an_index_so_cascades_never_scan(library_path: Path) -> None:
    SqliteLibraryStore(library_path)
    with raw_connection(library_path) as db:
        for table in TABLES:
            first_columns = {
                db.execute(
                    "SELECT name FROM pragma_index_info(?) WHERE seqno = 0", (index,)
                ).fetchone()[0]
                for (index,) in db.execute("SELECT name FROM pragma_index_list(?)", (table,))
            }
            key_columns = db.execute(
                'SELECT "from" FROM pragma_foreign_key_list(?) WHERE seq = 0', (table,)
            ).fetchall()
            for (column,) in key_columns:
                assert column in first_columns, (table, column)


def test_store_connections_turn_foreign_keys_on(store: SqliteLibraryStore) -> None:
    connection = store._connect()
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
    finally:
        connection.close()


def test_a_plain_connection_sees_a_consistent_file(library_path: Path) -> None:
    store = SqliteLibraryStore(library_path)
    store.add_camera(new_camera())
    store.add_recording(recording())
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_schema_that_fails_halfway_leaves_the_file_empty_and_reusable(
    library_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_schema = store_module._schema_sql()
    monkeypatch.setattr(store_module, "_schema_sql", lambda: real_schema + "\nCREATE TABLE (;")

    with pytest.raises(LibraryError):
        SqliteLibraryStore(library_path)

    assert _table_names(library_path) == set()
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0

    monkeypatch.undo()
    SqliteLibraryStore(library_path)
    assert _table_names(library_path) == set(TABLES)


# --- Upgrading from schema version 1: demo data only, so drop and recreate -------------


def _make_v1_library(path: Path) -> None:
    """A real version 1 library (the frozen v1 schema) holding a row in every table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with raw_connection(path) as db:
        db.executescript(V1_SCHEMA_FILE.read_text("utf-8"))
        db.execute("INSERT INTO cameras (id, name) VALUES ('loading-dock', 'Loading dock')")
        db.execute(
            "INSERT INTO recordings (id, camera_id, day, start_time, length_seconds, status) "
            "VALUES ('rec-1', 'loading-dock', '2026-10-29', 36000, 60, 'ready')"
        )
        db.execute(
            "INSERT INTO clips (id, recording_id, camera_id, day, start_time, start_seconds, "
            "end_seconds, label, zone, why_matched, thumbnail_url) VALUES ('clip-1', 'rec-1', "
            "'loading-dock', '2026-10-29', 36005, 5, 20, 'Person', NULL, '', NULL)"
        )
        db.execute("INSERT INTO clip_evidence VALUES ('clip-1', 0, 'dwell', 'Stayed')")
        db.execute("INSERT INTO clip_key_frames VALUES ('clip-1', 0, 5, NULL)")
        db.execute("INSERT INTO zones VALUES ('zone-1', 'loading-dock', 'Gate')")
        db.executemany("INSERT INTO zone_points VALUES ('zone-1', ?, 0.5, 0.5)", [(0,), (1,), (2,)])
        db.execute(
            "INSERT INTO saved_clips VALUES ('saved-1', 'clip-1', '', "
            "'2026-10-30T09:00:00.000000Z')"
        )


def _v1_row_counts(path: Path) -> dict[str, int]:
    with raw_connection(path) as db:
        return {  # fixed v1 table names, never input
            table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in sorted(V1_TABLES)
        }


def _schema_objects(path: Path) -> list[tuple[str, str, str | None]]:
    with raw_connection(path) as db:
        return sorted(db.execute("SELECT type, name, sql FROM sqlite_schema").fetchall())


def test_the_v1_fixture_is_a_real_v1_library(library_path: Path) -> None:
    _make_v1_library(library_path)
    assert _table_names(library_path) == V1_TABLES
    assert _v1_row_counts(library_path) == {
        "cameras": 1,
        "clip_evidence": 1,
        "clip_key_frames": 1,
        "clips": 1,
        "recordings": 1,
        "saved_clips": 1,
        "zone_points": 3,
        "zones": 1,
    }
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_opening_a_v1_library_drops_it_and_creates_the_current_schema(
    library_path: Path, tmp_path: Path
) -> None:
    _make_v1_library(library_path)

    store = SqliteLibraryStore(library_path)

    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 4
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute("SELECT last_number FROM camera_sequence").fetchone()[0] == 0
    assert _table_names(library_path) == set(TABLES)
    rows = {table: count_rows(library_path, table) for table in TABLES}
    assert rows == {**dict.fromkeys(TABLES, 0), "camera_sequence": 1}
    # The very same schema a brand-new library gets: tables, indexes and triggers.
    fresh = tmp_path / "fresh" / "index.sqlite"
    SqliteLibraryStore(fresh)
    assert _schema_objects(library_path) == _schema_objects(fresh)
    # ...and the seed then refills it, numbering new cameras after the seeded ones.
    assert seed_demo_data(store, DEMO_SEED) is True
    assert [c.id for c in store.list_cameras()] == ["CAM-001", "CAM-002", "CAM-003"]
    assert store.add_camera(new_camera("Side yard")).id == "CAM-004"


def test_an_upgraded_library_is_not_dropped_again_on_the_next_open(library_path: Path) -> None:
    _make_v1_library(library_path)
    first = SqliteLibraryStore(library_path)
    seed_demo_data(first, DEMO_SEED)
    added = first.add_camera(new_camera("Side yard"))

    reopened = SqliteLibraryStore(library_path)

    assert reopened.get_camera(added.id) == added
    assert len(reopened.list_cameras()) == 4
    assert seed_demo_data(reopened, DEMO_SEED) is False


def test_a_failed_v1_upgrade_leaves_the_v1_library_exactly_as_it_was(
    library_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_v1_library(library_path)
    before = _schema_objects(library_path), _v1_row_counts(library_path)
    real_schema = store_module._schema_sql()
    monkeypatch.setattr(store_module, "_schema_sql", lambda: real_schema + "\nCREATE TABLE (;")

    with pytest.raises(LibraryError, match="could not be opened"):
        SqliteLibraryStore(library_path)

    assert (_schema_objects(library_path), _v1_row_counts(library_path)) == before
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
    monkeypatch.undo()
    SqliteLibraryStore(library_path)
    assert _table_names(library_path) == set(TABLES)


def test_the_upgrade_keeps_created_at_style_timestamps_well_formed(library_path: Path) -> None:
    """created_at, new in v2, is stored like saved_at: fixed-width UTC text ending in Z."""
    _make_v1_library(library_path)
    store = SqliteLibraryStore(library_path)
    store.add_camera(new_camera(created_at=datetime(2026, 10, 30, 9, 1, 2, tzinfo=UTC)))
    with raw_connection(library_path) as db:
        [(text,)] = db.execute("SELECT created_at FROM cameras").fetchall()
    assert text == "2026-10-30T09:01:02.000000Z"


# --- Upgrading from schema version 2 (no tracks, no status notes): drop and recreate ----

V2_TABLES = V1_TABLES | {"camera_sequence"}


def _make_v2_library(path: Path) -> None:
    """A real version 2 library (the frozen v2 schema) holding a row in every table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with raw_connection(path) as db:
        db.executescript(V2_SCHEMA_FILE.read_text("utf-8"))
        db.execute(
            "INSERT INTO cameras (id, number, name, ip, username, status, location, department,"
            " created_at) VALUES ('CAM-007', 7, 'Dock', '10.0.0.7', 'viewer', 'online', NULL,"
            " NULL, '2026-10-30T09:00:00.000000Z')"
        )
        db.execute(
            "INSERT INTO recordings (id, camera_id, day, start_time, length_seconds, status) "
            "VALUES ('rec-1', 'CAM-007', '2026-10-29', 36000, 60, 'ready')"
        )
        db.execute(
            "INSERT INTO clips (id, recording_id, camera_id, day, start_time, start_seconds, "
            "end_seconds, label, zone, why_matched, thumbnail_url) VALUES ('clip-1', 'rec-1', "
            "'CAM-007', '2026-10-29', 36005, 5, 20, 'Person', NULL, '', NULL)"
        )
        db.execute("INSERT INTO clip_evidence VALUES ('clip-1', 0, 'dwell', 'Stayed')")
        db.execute("INSERT INTO clip_key_frames VALUES ('clip-1', 0, 5, NULL)")
        db.execute("INSERT INTO zones VALUES ('zone-1', 'CAM-007', 'Gate')")
        db.executemany("INSERT INTO zone_points VALUES ('zone-1', ?, 0.5, 0.5)", [(0,), (1,), (2,)])
        db.execute(
            "INSERT INTO saved_clips VALUES ('saved-1', 'clip-1', '', "
            "'2026-10-30T09:00:00.000000Z')"
        )


def _v2_row_counts(path: Path) -> dict[str, int]:
    with raw_connection(path) as db:
        return {  # fixed v2 table names, never input
            table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in sorted(V2_TABLES)
        }


def test_the_v2_fixture_is_a_real_v2_library(library_path: Path) -> None:
    _make_v2_library(library_path)
    assert _table_names(library_path) == V2_TABLES
    assert _v2_row_counts(library_path) == {
        "camera_sequence": 1,
        "cameras": 1,
        "clip_evidence": 1,
        "clip_key_frames": 1,
        "clips": 1,
        "recordings": 1,
        "saved_clips": 1,
        "zone_points": 3,
        "zones": 1,
    }
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT last_number FROM camera_sequence").fetchone()[0] == 7


def test_opening_a_v2_library_drops_it_and_creates_v3_cleanly(
    library_path: Path, tmp_path: Path
) -> None:
    _make_v2_library(library_path)

    store = SqliteLibraryStore(library_path)

    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 4
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        # The sequence starts again: the old cameras are gone, so no id can clash.
        assert db.execute("SELECT last_number FROM camera_sequence").fetchone()[0] == 0
    assert _table_names(library_path) == set(TABLES)
    rows = {table: count_rows(library_path, table) for table in TABLES}
    assert rows == {**dict.fromkeys(TABLES, 0), "camera_sequence": 1}
    fresh = tmp_path / "fresh" / "index.sqlite"
    SqliteLibraryStore(fresh)
    assert _schema_objects(library_path) == _schema_objects(fresh)
    assert seed_demo_data(store, DEMO_SEED) is True
    assert [c.id for c in store.list_cameras()] == ["CAM-001", "CAM-002", "CAM-003"]
    assert store.add_camera(new_camera("Side yard")).id == "CAM-004"


def test_a_failed_v2_upgrade_leaves_the_v2_library_exactly_as_it_was(
    library_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_v2_library(library_path)
    before = _schema_objects(library_path), _v2_row_counts(library_path)
    real_schema = store_module._schema_sql()
    monkeypatch.setattr(store_module, "_schema_sql", lambda: real_schema + "\nCREATE TABLE (;")

    with pytest.raises(LibraryError, match="could not be opened"):
        SqliteLibraryStore(library_path)

    assert (_schema_objects(library_path), _v2_row_counts(library_path)) == before
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    monkeypatch.undo()
    SqliteLibraryStore(library_path)
    assert _table_names(library_path) == set(TABLES)


def test_every_older_version_has_a_way_to_the_current_one() -> None:
    """Each version below the current one is either migrated or dropped, never stranded."""
    for version in range(1, SCHEMA_VERSION):
        dropped = version in store_module._DROP_TABLES_OF_VERSION
        migrated = all(step in store_module._MIGRATIONS for step in range(version, SCHEMA_VERSION))
        assert dropped or migrated, version
