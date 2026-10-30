"""Creating, reopening and refusing library databases; the schema's version and indexes."""

import re
from pathlib import Path

import pytest
from db_library_helpers import TABLES, camera, raw_connection, recording

from askfootage.adapters.sqlite import store as store_module
from askfootage.adapters.sqlite.store import SCHEMA_VERSION, SqliteLibraryStore
from askfootage.ports.library_store import LibraryError

SCHEMA_FILE = Path(store_module.__file__).with_name("schema.sql")


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
    first.add_camera(camera())
    first.add_recording(recording())

    second = SqliteLibraryStore(library_path)
    third = SqliteLibraryStore(library_path)

    assert second.list_cameras() == [camera()]
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
    # The only free-text name columns are a camera's and a zone's, which name places.
    assert {column for column in columns if "name" in column} == {"name"}


# The common queries must be answered from an index, in index order (no sort step).
_INDEXED_QUERIES = {
    "list_recordings": (store_module._RECORDINGS_ON_DAY, ("cam-1", "2026-10-29")),
    "summarise_days": (store_module._DAY_SUMMARIES, ("cam-1", "2026-10-24", "2026-10-30")),
    "list_clips": (store_module._CLIPS_ON_DAY, ("cam-1", "2026-10-29")),
    "all_zones": (store_module._ALL_ZONES, ()),
    "zones_of_camera": (store_module._ZONES_OF_CAMERA, ("cam-1",)),
    "other_zone_names": (store_module._OTHER_ZONE_NAMES, ("cam-1", "zone-1")),
    "saved_clips": (store_module._SAVED_CLIPS, ()),
    "saved_clips_on_day": (store_module._SAVED_CLIPS_ON_DAY, ("2026-10-29",)),
    "clip_already_saved": (store_module._CLIP_ALREADY_SAVED, ("clip-1",)),
    "evidence_of_clips": (store_module._EVIDENCE_OF_CLIPS, ('["clip-1"]',)),
    "key_frames_of_clips": (store_module._KEY_FRAMES_OF_CLIPS, ('["clip-1"]',)),
    "points_of_zones": (store_module._POINTS_OF_ZONES, ('["zone-1"]',)),
}


@pytest.mark.parametrize("query", sorted(_INDEXED_QUERIES))
def test_common_queries_use_an_index_and_need_no_sort(library_path: Path, query: str) -> None:
    SqliteLibraryStore(library_path)
    sql, params = _INDEXED_QUERIES[query]
    with raw_connection(library_path) as db:
        plan = " | ".join(row[3] for row in db.execute(f"EXPLAIN QUERY PLAN {sql}", params))

    assert "USING" in plan and "INDEX" in plan, plan
    assert "TEMP B-TREE" not in plan, plan
    assert not re.search(r"SCAN (clips|recordings|c)(?! USING)", plan), plan


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
    store.add_camera(camera())
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
