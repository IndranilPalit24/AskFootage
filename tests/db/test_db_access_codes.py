"""Demo access codes: the table, the v5 -> v6 migration, the store and the CLI.

Every database is a fresh file in tmp_path.
"""

import io
import sqlite3
from pathlib import Path

import pytest
from db_library_helpers import ALL_TABLES, raw_connection

from askfootage.adapters.sqlite import access_codes
from askfootage.adapters.sqlite.access_codes import SqliteAccessCodeStore
from askfootage.adapters.sqlite.store import SCHEMA_VERSION, SqliteLibraryStore
from askfootage.interfaces.cli import access as cli
from askfootage.settings import Settings

STAMP = "2026-11-02T10:00:00.000000Z"
HEX8, HEX64, HEX32 = "ab12cd34", "a" * 64, "b" * 32
INJECTION = "x'); DROP TABLE demo_access_codes;--"


@pytest.fixture
def codes(store: SqliteLibraryStore) -> SqliteAccessCodeStore:
    return SqliteAccessCodeStore(store)


def _insert(db: sqlite3.Connection, *values: object) -> None:
    db.execute(
        "INSERT INTO demo_access_codes (id, code_hash, salt, label, created_at, revoked_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        values,
    )


def _good(**changes: object) -> tuple[object, ...]:
    row = {
        "id": HEX8,
        "code_hash": HEX64,
        "salt": HEX32,
        "label": "judges",
        "created_at": STAMP,
        "revoked_at": None,
    }
    row.update(changes)
    return tuple(row.values())


# --- Schema and migration ----------------------------------------------------------------


def test_the_table_exists_in_a_new_library_at_version_6(library_path: Path) -> None:
    SqliteLibraryStore(library_path)
    SqliteLibraryStore(library_path)  # opening again is repeatable
    assert SCHEMA_VERSION == 6
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    assert set(ALL_TABLES) <= names and "demo_access_codes" in names


def test_a_v5_library_is_upgraded_in_place_and_keeps_its_rows(library_path: Path) -> None:
    from db_library_helpers import new_camera

    store = SqliteLibraryStore(library_path)
    store.add_camera(new_camera())
    with raw_connection(library_path) as db:
        db.executescript("DROP TABLE demo_access_codes; PRAGMA user_version = 5;")

    upgraded = SqliteLibraryStore(library_path)

    assert [c.id for c in upgraded.list_cameras()] == ["CAM-001"]
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert SqliteAccessCodeStore(upgraded).list_codes() == []


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "short"},
        {"id": "ABCDEF12"},  # upper case
        {"id": "ab12cd3g"},
        {"code_hash": "a" * 63},
        {"code_hash": "g" * 64},
        {"salt": "b" * 31},
        {"salt": "z" * 32},
        {"label": ""},
        {"label": " padded "},
        {"label": "x" * 41},
        {"created_at": "2026-11-02"},
        {"created_at": "2026-13-45T10:00:00.000000Z"},
        {"revoked_at": "yesterday"},
        {"revoked_at": "2026-11-01T10:00:00.000000Z"},  # before created_at
        {"label": None},
        {"code_hash": None},
        {"salt": None},
        {"created_at": None},
        {"id": 5},  # STRICT: wrong type
    ],
)
def test_every_constraint_rejects_bad_rows(library_path: Path, bad: dict[str, object]) -> None:
    SqliteLibraryStore(library_path)
    with raw_connection(library_path) as db:
        _insert(db, *_good())  # the good row is fine
        db.execute("DELETE FROM demo_access_codes")
        with pytest.raises(sqlite3.IntegrityError):
            _insert(db, *_good(**bad))
        assert db.execute("SELECT count(*) FROM demo_access_codes").fetchone()[0] == 0


def test_the_primary_key_rejects_a_repeated_id(library_path: Path) -> None:
    SqliteLibraryStore(library_path)
    with raw_connection(library_path) as db:
        _insert(db, *_good())
        with pytest.raises(sqlite3.IntegrityError):
            _insert(db, *_good())


def test_a_revoked_row_with_a_valid_time_is_accepted(library_path: Path) -> None:
    SqliteLibraryStore(library_path)
    with raw_connection(library_path) as db:
        _insert(db, *_good(revoked_at="2026-11-03T00:00:00.000000Z"))


# --- Store -------------------------------------------------------------------------------


def test_create_returns_a_six_digit_code_once_and_stores_only_a_hash(
    codes: SqliteAccessCodeStore, library_path: Path
) -> None:
    made = codes.create_code("owner")

    assert len(made.code) == 6 and made.code.isdigit() and made.label == "owner"
    assert len(made.id) == 8
    with raw_connection(library_path) as db:
        row = db.execute("SELECT * FROM demo_access_codes").fetchone()
        dump = "".join(str(v) for v in row)
    assert made.code not in dump.replace(row[1], "").replace(row[2], "")  # not id, label, time
    assert row[3] == "owner" and row[5] is None
    assert len(row[1]) == 64 and len(row[2]) == 32


def test_codes_are_zero_padded_digits(
    codes: SqliteAccessCodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(access_codes.secrets, "randbelow", lambda _n: 42)
    made = codes.create_code("judges")
    assert made.code == "000042"
    assert codes.verify_code("000042") is True


def test_verify_accepts_the_code_and_refuses_everything_else(
    codes: SqliteAccessCodeStore,
) -> None:
    made = codes.create_code("judges")
    wrong = f"{(int(made.code) + 1) % 10**6:06d}"

    assert codes.verify_code(made.code) is True
    assert codes.verify_code(wrong) is False
    for bad in ("", "12345", "1234567", "12345a", "١٢٣٤٥٦", " 123456", "123456\n", INJECTION):
        assert codes.verify_code(bad) is False
    assert codes.verify_code(None) is False  # type: ignore[arg-type]
    assert codes.verify_code(123456) is False  # type: ignore[arg-type]


def test_verify_finds_any_of_several_codes(codes: SqliteAccessCodeStore) -> None:
    first, second = codes.create_code("owner"), codes.create_code("judges")
    assert first.code != second.code
    assert codes.verify_code(first.code) and codes.verify_code(second.code)


def test_a_new_code_never_repeats_an_active_one(
    codes: SqliteAccessCodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    draws = iter([7, 7, 7, 8])
    monkeypatch.setattr(access_codes.secrets, "randbelow", lambda _n: next(draws))
    assert codes.create_code("a").code == "000007"
    assert codes.create_code("b").code == "000008"


def test_revoke_stops_a_code_and_is_reported_once(codes: SqliteAccessCodeStore) -> None:
    made = codes.create_code("judges")
    other = codes.create_code("owner")

    assert codes.revoke_code(made.id) is True
    assert codes.verify_code(made.code) is False
    assert codes.verify_code(other.code) is True
    assert codes.revoke_code(made.id) is False  # already revoked
    assert codes.revoke_code("00000000") is False  # unknown
    assert codes.revoke_code(INJECTION) is False


def test_a_revoked_code_may_be_drawn_again_for_a_new_row(
    codes: SqliteAccessCodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(access_codes.secrets, "randbelow", lambda _n: 5)
    old = codes.create_code("a")
    codes.revoke_code(old.id)
    new = codes.create_code("b")
    assert new.code == old.code and codes.verify_code(new.code) is True


def test_list_shows_label_time_and_state_and_never_the_code(
    codes: SqliteAccessCodeStore,
) -> None:
    a, b = codes.create_code("owner"), codes.create_code("judges")
    codes.revoke_code(b.id)

    listed = codes.list_codes()

    assert [(i.id, i.label, i.revoked) for i in listed] == [
        (a.id, "owner", False),
        (b.id, "judges", True),
    ]
    assert all(i.created_at.tzinfo is not None for i in listed)
    assert a.code not in repr(listed) and b.code not in repr(listed)


@pytest.mark.parametrize("label", ["", "   ", " owner", "owner ", "x" * 41])
def test_create_refuses_a_bad_label_and_stores_nothing(
    codes: SqliteAccessCodeStore, label: str
) -> None:
    with pytest.raises(ValueError, match="label"):
        codes.create_code(label)
    assert codes.list_codes() == []


def test_a_label_with_sql_in_it_is_stored_as_plain_text(
    codes: SqliteAccessCodeStore, library_path: Path
) -> None:
    made = codes.create_code(INJECTION)

    assert [i.label for i in codes.list_codes()] == [INJECTION]
    assert codes.verify_code(made.code) is True
    with raw_connection(library_path) as db:
        assert db.execute("SELECT count(*) FROM demo_access_codes").fetchone()[0] == 1


def test_codes_survive_reopening_the_library(library_path: Path) -> None:
    made = SqliteAccessCodeStore(SqliteLibraryStore(library_path)).create_code("owner")
    again = SqliteAccessCodeStore(SqliteLibraryStore(library_path))
    assert again.verify_code(made.code) is True


def test_other_tables_are_untouched_and_deleting_a_camera_keeps_codes(
    codes: SqliteAccessCodeStore, store: SqliteLibraryStore, library_path: Path
) -> None:
    from db_library_helpers import new_camera

    store.add_camera(new_camera())
    made = codes.create_code("owner")
    store.delete_camera("CAM-001")
    assert codes.verify_code(made.code) is True
    with raw_connection(library_path) as db:
        assert db.execute("SELECT count(*) FROM cameras").fetchone()[0] == 0


# --- CLI ---------------------------------------------------------------------------------


def _run(path: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main([*argv, "--database", str(path)], out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_cli_create_list_revoke(library_path: Path) -> None:
    SqliteLibraryStore(library_path)

    code, out, _ = _run(library_path, "--create", "--label", "judges")
    assert code == 0
    plain = out.split("code ")[1].split()[0]
    code_id = out.split("id ")[1].split()[0]
    assert len(plain) == 6 and plain.isdigit()
    store = SqliteAccessCodeStore(SqliteLibraryStore(library_path))
    assert store.verify_code(plain) is True

    code, listing, _ = _run(library_path, "--list")
    assert code == 0 and "judges" in listing and "active" in listing and plain not in listing

    code, out, _ = _run(library_path, "--revoke", code_id)
    assert code == 0 and "revoked" in out
    assert store.verify_code(plain) is False
    code, listing, _ = _run(library_path, "--list")
    assert "revoked" in listing and plain not in listing

    code, _, err = _run(library_path, "--revoke", code_id)
    assert code == 1 and "no active code" in err


def test_cli_refuses_a_missing_file_and_never_creates_it(tmp_path: Path) -> None:
    missing = tmp_path / "nope" / "library.sqlite"
    code, _, err = _run(missing, "--list")
    assert code == 1 and "does not exist" in err
    assert not missing.exists() and not missing.parent.exists()


def test_cli_refuses_a_bad_label_without_a_traceback(library_path: Path) -> None:
    SqliteLibraryStore(library_path)
    code, out, err = _run(library_path, "--create", "--label", "x" * 41)
    assert code == 1 and out == "" and "Traceback" not in err


@pytest.mark.parametrize(
    "argv",
    [[], ["--create"], ["--list", "--label", "x"], ["--create", "--list"], ["--revoke"]],
)
def test_cli_bad_command_lines_exit_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(argv, out=io.StringIO(), err=io.StringIO())
    assert stopped.value.code == 2


def test_cli_picks_the_real_library_from_settings(tmp_path: Path) -> None:
    real = tmp_path / "real" / "library.sqlite"
    SqliteLibraryStore(real)
    settings = Settings(data_dir=tmp_path)
    out = io.StringIO()
    assert cli.main(["--create", "--label", "owner"], settings=settings, out=out) == 0
    assert SqliteAccessCodeStore(SqliteLibraryStore(real)).list_codes()[0].label == "owner"
