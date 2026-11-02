"""The volume's command line, its setting, the app wiring and the v4 -> v5 migration.

Every database is a copy in tmp_path. The real library (data/real/library.sqlite) is only ever
read, to be copied; the first test proves its bytes are unchanged by the migration test.
"""

import hashlib
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from db_library_helpers import (
    CREATED_AT,
    REPO_ROOT,
    clip,
    dump,
    new_camera,
    raw_connection,
    recording,
)
from fastapi.testclient import TestClient

from askfootage.adapters.sqlite.store import SCHEMA_VERSION, SqliteLibraryStore
from askfootage.adapters.sqlite.volume_seed import (
    CAMERA_COUNT,
    DEMO_DAY,
    add_volume,
    generate_volume,
    remove_volume,
    volume_status,
)
from askfootage.interfaces.api.app import create_app, open_demo_library
from askfootage.interfaces.cli import volume as cli
from askfootage.interfaces.real_clips import create_app as create_real_app
from askfootage.settings import Settings, load_settings

REAL_LIBRARY = REPO_ROOT / "data" / "real" / "library.sqlite"
needs_real_library = pytest.mark.skipif(
    not REAL_LIBRARY.is_file(), reason="data/real/library.sqlite is not on this machine"
)
OLD_COLUMNS = {
    "cameras": "id, number, name, ip, username, status, location, department, created_at",
    "recordings": "id, camera_id, day, start_time, length_seconds, status, status_note",
    "zones": "id, camera_id, name",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def real_copy(tmp_path: Path) -> Path:
    """A copy of the real library holding only its real rows, never the original.

    The documented demo start adds the generated volume to data/real/library.sqlite, so the
    copy may already hold it; it is removed from the COPY so every test starts from the real
    rows whatever the machine has been used for.
    """
    if not REAL_LIBRARY.is_file():
        pytest.skip("data/real/library.sqlite is not on this machine")
    target = tmp_path / "real" / "library.sqlite"
    target.parent.mkdir()
    shutil.copy(REAL_LIBRARY, target)
    with raw_connection(target) as db:
        has_origin = any(row[1] == "origin" for row in db.execute("PRAGMA table_info(cameras)"))
    if has_origin:
        remove_volume(SqliteLibraryStore(target))
    return target


# --- Migration -----------------------------------------------------------------------------


@needs_real_library
def test_migrating_a_copy_of_the_real_library_keeps_every_row_and_adds_origin(
    real_copy: Path,
) -> None:
    original_hash = _sha256(REAL_LIBRARY)
    with raw_connection(real_copy) as db:
        old_version = db.execute("PRAGMA user_version").fetchone()[0]
        before = {t: db.execute(f"SELECT {c} FROM {t}").fetchall() for t, c in OLD_COLUMNS.items()}  # noqa: S608
        other = {
            t: db.execute(f"SELECT * FROM {t}").fetchall()  # noqa: S608
            for t in ("clips", "clip_evidence", "clip_key_frames", "tracks", "track_points")
        }
    assert old_version in (4, SCHEMA_VERSION)

    store = SqliteLibraryStore(real_copy)

    with raw_connection(real_copy) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 5
        for table, columns in OLD_COLUMNS.items():
            assert db.execute(f"SELECT {columns} FROM {table}").fetchall() == before[table]  # noqa: S608
            assert {o for (o,) in db.execute(f"SELECT origin FROM {table}")} <= {"real"}  # noqa: S608
        assert {r for r in db.execute("SELECT has_footage FROM recordings")} == {(1,)}
        for table, rows in other.items():
            assert db.execute(f"SELECT * FROM {table}").fetchall() == rows  # noqa: S608
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert [r.has_footage for r in store.list_recordings(None, DEMO_DAY)] == [True, True]
    assert _sha256(REAL_LIBRARY) == original_hash  # the original is untouched


@needs_real_library
def test_the_volume_adds_to_and_removes_from_a_copy_of_the_real_library(real_copy: Path) -> None:
    store = SqliteLibraryStore(real_copy)  # migrates the copy
    before = dump(real_copy)
    code, out, _ = _run("--database", str(real_copy), "--add")
    assert code == 0 and "volume added" in out
    status = volume_status(store)
    assert status["cameras"] == {"real": 1, "demo_volume": CAMERA_COUNT}
    assert status["tracks"] == {"real": 13, "demo_volume": 0}
    assert status["clips"]["demo_volume"] == status["saved_clips"]["demo_volume"] == 0
    assert store.get_camera("CAM-002") is not None
    assert store.get_recording("clip1") is not None and store.get_recording("clip2") is not None
    code, out, _ = _run("--database", str(real_copy), "--remove")
    assert code == 0 and "volume removed" in out
    assert dump(real_copy) == before


def test_a_v4_database_is_upgraded_in_place(tmp_path: Path) -> None:
    """Build a v4 file from the current schema (drop what v5 added), then open it."""
    path = tmp_path / "v4.sqlite"
    store = SqliteLibraryStore(path)
    store.add_camera(new_camera())
    store.add_recording(recording())
    with raw_connection(path) as db:
        db.executescript(
            """
            DROP TABLE volume_state;
            ALTER TABLE cameras DROP COLUMN origin;
            ALTER TABLE zones DROP COLUMN origin;
            ALTER TABLE recordings DROP COLUMN origin;
            ALTER TABLE recordings DROP COLUMN has_footage;
            PRAGMA user_version = 4;
            """
        )
    fresh_columns = _columns(path.parent / "fresh.sqlite")
    upgraded = SqliteLibraryStore(path)
    assert _columns(path) == fresh_columns
    assert [c.id for c in upgraded.list_cameras()] == ["CAM-001"]
    assert upgraded.get_recording("rec-1").has_footage is True  # type: ignore[union-attr]
    assert add_and_remove_round_trip(upgraded)


def add_and_remove_round_trip(store: SqliteLibraryStore) -> bool:
    before = dump(store.path)
    add_volume(store)
    remove_volume(store)
    return dump(store.path) == before


def _columns(path: Path) -> dict[str, list[tuple[object, ...]]]:
    if not path.exists():
        SqliteLibraryStore(path)
    with raw_connection(path) as db:
        tables = [t for (t,) in db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")]
        return {
            t: [r[1:] for r in db.execute("SELECT * FROM pragma_table_info(?)", (t,))]
            for t in sorted(tables)
        }


# --- Settings ----------------------------------------------------------------------------------


def test_the_setting_is_off_by_default_and_on_with_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ASKFOOTAGE_DEMO_VOLUME", raising=False)
    assert load_settings(env_file=None).demo_volume is False
    monkeypatch.setenv("ASKFOOTAGE_DEMO_VOLUME", "1")
    assert load_settings(env_file=None).demo_volume is True


# --- The command line -----------------------------------------------------------------------


@pytest.fixture
def library(tmp_path: Path) -> Path:
    path = tmp_path / "lib.sqlite"
    SqliteLibraryStore(path)
    return path


def test_status_add_remove_through_the_command_line(library: Path) -> None:
    before = dump(library)
    code, out, err = _run("--database", str(library), "--status")
    assert code == 0 and err == "" and "demo_volume" in out
    assert [line.split()[0] for line in out.splitlines()[1:3]] == ["cameras", "zones"]

    code, out, _ = _run("--database", str(library), "--add")
    assert code == 0 and "volume added" in out
    assert f"{CAMERA_COUNT}" in next(
        line for line in out.splitlines() if line.startswith("cameras")
    )
    after_add = dump(library)

    code, out, _ = _run("--database", str(library), "--add")  # idempotent
    assert code == 0 and "nothing changed" in out
    assert dump(library) == after_add

    code, out, _ = _run("--database", str(library), "--remove")
    assert code == 0 and "volume removed" in out
    assert dump(library) == before

    code, out, _ = _run("--database", str(library), "--remove")
    assert code == 0 and "nothing changed" in out


def test_the_command_line_never_creates_a_missing_library(tmp_path: Path) -> None:
    missing = tmp_path / "nope" / "x.sqlite"
    code, _, err = _run("--database", str(missing), "--add")
    assert code == 1 and "does not exist" in err
    assert not missing.exists() and not missing.parent.exists()


def test_the_command_line_needs_exactly_one_action() -> None:
    for argv in ([], ["--add", "--remove"], ["--status", "--add"]):
        with pytest.raises(SystemExit) as stop:
            cli.main(argv, out=io.StringIO(), err=io.StringIO())
        assert stop.value.code == 2


def test_the_library_comes_from_settings_data_dir(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, DATA_DIR=str(tmp_path))  # type: ignore[call-arg]
    (tmp_path / "real").mkdir()
    SqliteLibraryStore(tmp_path / "real" / "library.sqlite")
    SqliteLibraryStore(tmp_path / "demo.sqlite")
    out = io.StringIO()
    assert cli.main(["--add"], settings=settings, out=out, err=io.StringIO()) == 0
    assert (
        volume_status(SqliteLibraryStore(tmp_path / "real" / "library.sqlite"))["cameras"][
            "demo_volume"
        ]
        == CAMERA_COUNT
    )
    assert (
        volume_status(SqliteLibraryStore(tmp_path / "demo.sqlite"))["cameras"]["demo_volume"] == 0
    )
    assert cli.main(["--demo", "--add"], settings=settings, out=out, err=io.StringIO()) == 0
    assert (
        volume_status(SqliteLibraryStore(tmp_path / "demo.sqlite"))["cameras"]["demo_volume"]
        == CAMERA_COUNT
    )


def test_a_refused_remove_exits_one_with_a_message(library: Path) -> None:
    store = SqliteLibraryStore(library)
    _run("--database", str(library), "--add")
    victim = generate_volume(1).recordings[0]
    store.add_clip(clip("mine", recording_id=victim.id, day=victim.day))
    store.add_saved_clip("s1", "mine", "keep", CREATED_AT)
    code, _, err = _run("--database", str(library), "--remove")
    assert code == 1 and "saved clip" in err and str(library) not in err


def test_the_module_runs_with_dash_m(library: Path) -> None:
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "askfootage.interfaces.cli.volume",
            "--database",
            str(library),
            "--status",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "cameras" in result.stdout


# --- Determinism across processes ------------------------------------------------------------


def test_the_generator_gives_identical_bytes_in_separate_processes() -> None:
    code = (
        "import hashlib;from askfootage.adapters.sqlite.volume_seed import generate_volume;"
        "print(hashlib.sha256(repr(generate_volume(2)).encode()).hexdigest())"
    )
    hashes = set()
    for seed in ("0", "1", "12345"):
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        hashes.add(result.stdout.strip())
    assert len(hashes) == 1
    assert hashes == {hashlib.sha256(repr(generate_volume(2)).encode()).hexdigest()}


# --- App wiring --------------------------------------------------------------------------------


def test_demo_mode_serves_the_volume_only_when_the_setting_is_on(tmp_path: Path) -> None:
    plain = Settings(_env_file=None, DATA_DIR=str(tmp_path / "a"))  # type: ignore[call-arg]
    with TestClient(create_app(plain)) as client:
        assert len(client.get("/api/cameras").json()) == 3
    on = Settings(_env_file=None, DATA_DIR=str(tmp_path / "b"), ASKFOOTAGE_DEMO_VOLUME="1")  # type: ignore[call-arg]
    with TestClient(create_app(on)) as client:
        assert len(client.get("/api/cameras").json()) == 3 + CAMERA_COUNT
        again = open_demo_library(on)  # a second start adds nothing
        assert len(again.cameras.list_cameras()) == 3 + CAMERA_COUNT


@needs_real_library
def test_real_mode_serves_the_volume_only_when_asked_and_keeps_the_real_clips(
    real_copy: Path,
) -> None:
    data_dir = real_copy.parent
    with TestClient(create_real_app(data_dir, data_dir / "videos")) as client:
        assert len(client.get("/api/cameras").json()) == 1
    for _ in range(2):  # a second start adds nothing more
        with TestClient(create_real_app(data_dir, data_dir / "videos", demo_volume=True)) as client:
            cameras = client.get("/api/cameras").json()
            assert len(cameras) == 1 + CAMERA_COUNT
            days = client.get("/api/days").json()
            assert len(days) == 7
            recordings = client.get(f"/api/recordings?day={DEMO_DAY}").json()
            assert {"clip1", "clip2"} <= {r["id"] for r in recordings}
    store = SqliteLibraryStore(real_copy)
    real_ids = {r.id for r in store.list_recordings(None, DEMO_DAY) if r.has_footage}
    assert real_ids == {"clip1", "clip2"}
    assert volume_status(store)["tracks"] == {"real": 13, "demo_volume": 0}
