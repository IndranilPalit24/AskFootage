"""The camera registry: ids handed out in order and never reused, exact round trips,
status changes, deletes, names unique ignoring case, number order past 999, and counts."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest
from db_library_helpers import (
    CAM_1,
    CAM_2,
    NO_SUCH_CAMERA,
    clip,
    new_camera,
    raw_connection,
    recording,
    stored_camera,
    zone,
)

from askfootage.adapters.sqlite import store as store_module
from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.ports.library_store import (
    CAMERA_STATUSES,
    CameraCounts,
    CameraStatus,
    DuplicateError,
    LibraryError,
    NewCamera,
    camera_id_for,
)

INJECTION = "Robert'); DROP TABLE cameras;--"


def _set_sequence(path: Path, last_number: int) -> None:
    """Move camera_sequence up, as if that many cameras had been added (and deleted)."""
    with raw_connection(path) as db:
        db.execute("UPDATE camera_sequence SET last_number = ?", (last_number,))


# --- Adding, reading, ids ----------------------------------------------------------------


def test_add_camera_hands_out_ids_in_order_and_returns_what_get_returns(
    store: SqliteLibraryStore,
) -> None:
    first, second = new_camera("Front gate"), new_camera("Yard", status="standby")

    added = [store.add_camera(first), store.add_camera(second)]

    assert added == [stored_camera(CAM_1, first), stored_camera(CAM_2, second)]
    assert store.list_cameras() == added
    assert store.get_camera(CAM_1) == added[0]
    assert store.get_camera(CAM_2) == added[1]


def test_every_field_round_trips_exactly(store: SqliteLibraryStore) -> None:
    full = new_camera(
        "Quai d'Orsay · Tor 3 📷",
        ip="cam-backdoor.local",
        username="ops.viewer@site",
        status="offline",
        location="Warehouse, north side",
        department="Facilities",
        created_at=datetime(2026, 10, 22, 10, 15, 0, 123456, tzinfo=UTC),
    )
    bare = new_camera("Bare", location=None, department=None)

    assert store.add_camera(full) == stored_camera(CAM_1, full)
    assert store.add_camera(bare) == stored_camera(CAM_2, bare)

    assert store.get_camera(CAM_1) == stored_camera(CAM_1, full)
    got = store.get_camera(CAM_2)
    assert got is not None and got.location is None and got.department is None


def test_created_at_comes_back_aware_in_utc(store: SqliteLibraryStore) -> None:
    india = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 10, 30, 14, 42, 44, 500, tzinfo=india)

    returned = store.add_camera(new_camera(created_at=local))
    got = store.get_camera(returned.id)

    assert got == returned
    assert got is not None and got.created_at == local
    assert got.created_at.utcoffset() == timedelta(0)
    assert got.created_at == datetime(2026, 10, 30, 9, 12, 44, 500, tzinfo=UTC)


def test_unknown_or_malformed_camera_ids_find_nothing(store: SqliteLibraryStore) -> None:
    store.add_camera(new_camera())
    for camera_id in (NO_SUCH_CAMERA, "loading-dock", "CAM-1", "CAM-0001", "cam-001", INJECTION):
        assert store.get_camera(camera_id) is None, camera_id
        assert store.set_camera_status(camera_id, "offline") is None, camera_id
        assert store.delete_camera(camera_id) is False, camera_id
    assert [c.id for c in store.list_cameras()] == [CAM_1]


def test_an_empty_library_has_no_cameras(store: SqliteLibraryStore) -> None:
    assert store.list_cameras() == []
    assert store.camera_counts() == {}


# --- Ids are never reused ------------------------------------------------------------------


def test_deleting_the_newest_camera_never_frees_its_number(store: SqliteLibraryStore) -> None:
    for name in ("One", "Two", "Three"):
        store.add_camera(new_camera(name))
    assert store.delete_camera("CAM-003") is True

    added = store.add_camera(new_camera("Four"))

    assert added.id == "CAM-004"
    assert [c.id for c in store.list_cameras()] == [CAM_1, CAM_2, "CAM-004"]


def test_deleting_every_camera_never_restarts_the_count(store: SqliteLibraryStore) -> None:
    for name in ("One", "Two"):
        store.add_camera(new_camera(name))
    assert store.delete_camera(CAM_1) and store.delete_camera(CAM_2)
    assert store.list_cameras() == []

    assert store.add_camera(new_camera("One")).id == "CAM-003"


def test_the_count_survives_a_restart(library_path: Path) -> None:
    first = SqliteLibraryStore(library_path)
    first.add_camera(new_camera("One"))
    first.add_camera(new_camera("Two"))
    first.delete_camera(CAM_2)

    restarted = SqliteLibraryStore(library_path)

    assert restarted.add_camera(new_camera("Three")).id == "CAM-003"


def test_three_hundred_cameras_list_in_number_order(store: SqliteLibraryStore) -> None:
    added = [store.add_camera(new_camera(f"Camera {n}")).id for n in range(1, 301)]

    listed = [c.id for c in store.list_cameras()]

    assert added == listed == [camera_id_for(n) for n in range(1, 301)]
    assert listed.index("CAM-100") == listed.index("CAM-099") + 1
    assert listed[-1] == "CAM-300"
    assert list(store.camera_counts()) == listed


def test_ids_past_999_grow_a_digit_and_still_sort_by_number(
    store: SqliteLibraryStore, library_path: Path
) -> None:
    store.add_camera(new_camera("First"))
    _set_sequence(library_path, 997)  # as if CAM-002 to CAM-997 came and went

    added = [store.add_camera(new_camera(name)).id for name in ("A", "B", "C")]

    assert added == ["CAM-998", "CAM-999", "CAM-1000"]
    # As text, "CAM-1000" < "CAM-998"; the registry orders by the number.
    assert [c.id for c in store.list_cameras()] == [CAM_1, *added]
    assert list(store.camera_counts()) == [CAM_1, *added]


def test_all_camera_recordings_break_start_time_ties_by_camera_number(
    store: SqliteLibraryStore, library_path: Path
) -> None:
    _set_sequence(library_path, 998)
    assert store.add_camera(new_camera("Nine nine nine")).id == "CAM-999"
    assert store.add_camera(new_camera("One thousand")).id == "CAM-1000"
    # Same day and start time; ids chosen so that id order would put CAM-1000's first.
    store.add_recording(recording("rec-b", "CAM-999", start_time=time(8)))
    store.add_recording(recording("rec-a", "CAM-1000", start_time=time(8)))
    store.add_recording(recording("rec-c", "CAM-1000", start_time=time(7)))

    listed = store.list_recordings(None, date(2026, 10, 29))

    assert [(r.start_time, r.camera, r.id) for r in listed] == [
        (time(7), "CAM-1000", "rec-c"),
        (time(8), "CAM-999", "rec-b"),
        (time(8), "CAM-1000", "rec-a"),
    ]


# --- Status ---------------------------------------------------------------------------------


@pytest.mark.parametrize("status", CAMERA_STATUSES)
def test_set_camera_status_returns_the_camera_after_the_change(
    store: SqliteLibraryStore, status: CameraStatus
) -> None:
    before = store.add_camera(new_camera(status="standby"))
    other = store.add_camera(new_camera("Yard", status="online"))

    changed = store.set_camera_status(CAM_1, status)

    assert changed == stored_camera(CAM_1, new_camera(status=status))
    assert changed is not None and changed.created_at == before.created_at
    assert store.get_camera(CAM_1) == changed
    assert store.get_camera(CAM_2) == other  # untouched


@pytest.mark.parametrize("status", ["ONLINE", "deleted", "", "online "])
def test_set_camera_status_refuses_an_unknown_status_and_changes_nothing(
    store: SqliteLibraryStore, status: str
) -> None:
    before = store.add_camera(new_camera())
    with pytest.raises(ValueError, match="status"):
        store.set_camera_status(CAM_1, status)  # type: ignore[arg-type]  # deliberately bad
    assert store.get_camera(CAM_1) == before


# --- Delete ----------------------------------------------------------------------------------


def test_delete_camera_is_true_once_then_false(store: SqliteLibraryStore) -> None:
    store.add_camera(new_camera())
    kept = store.add_camera(new_camera("Yard"))

    assert store.delete_camera(CAM_1) is True
    assert store.delete_camera(CAM_1) is False

    assert store.get_camera(CAM_1) is None
    assert store.list_cameras() == [kept]


def test_a_deleted_cameras_name_can_be_used_again(store: SqliteLibraryStore) -> None:
    store.add_camera(new_camera("Front gate"))
    store.delete_camera(CAM_1)
    assert store.add_camera(new_camera("FRONT GATE")).id == CAM_2


# --- Names -----------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Front gate", "front gate", "FRONT GATE", "fRONT gATE"])
def test_names_clash_ignoring_case(store: SqliteLibraryStore, name: str) -> None:
    store.add_camera(new_camera("Front gate"))
    with pytest.raises(DuplicateError, match="name"):
        store.add_camera(new_camera(name))
    assert [c.name for c in store.list_cameras()] == ["Front gate"]


@pytest.mark.parametrize(
    ("first", "second"),
    [("Straße", "STRASSE"), ("ÉCLUSE", "écluse"), ("ΟΔΟΣ", "οδος"), ("Ǆ gate", "ǆ GATE")],
    ids=["sharp-s", "accented", "final-sigma", "digraph"],
)
def test_names_clash_by_unicode_casefold_not_just_ascii(
    store: SqliteLibraryStore, first: str, second: str
) -> None:
    # SQLite's lower() folds ASCII only, so the schema's lower(name) index lets each of
    # these pairs through; only the store's str.casefold check can refuse the second.
    assert first.casefold() == second.casefold()
    with closing(sqlite3.connect(":memory:")) as sqlite_only:
        lowered = sqlite_only.execute("SELECT lower(?), lower(?)", (first, second)).fetchone()
    assert lowered[0] != lowered[1]
    store.add_camera(new_camera(first))
    with pytest.raises(DuplicateError, match="name"):
        store.add_camera(new_camera(second))
    assert [c.name for c in store.list_cameras()] == [first]


def test_a_refused_name_does_not_use_up_a_number(store: SqliteLibraryStore) -> None:
    store.add_camera(new_camera("Front gate"))
    with pytest.raises(DuplicateError):
        store.add_camera(new_camera("FRONT GATE"))
    assert store.add_camera(new_camera("Yard")).id == CAM_2


def test_names_differing_only_in_spacing_do_not_clash(store: SqliteLibraryStore) -> None:
    """Only case is ignored; trimming is the API's to decide (it stores names trimmed)."""
    store.add_camera(new_camera("Front gate"))
    store.add_camera(new_camera("Front gate "))
    store.add_camera(new_camera("Front  gate"))
    assert len(store.list_cameras()) == 3


def test_a_name_keeps_the_case_it_was_given(store: SqliteLibraryStore) -> None:
    added = store.add_camera(new_camera("fRoNt GaTe"))
    assert added.name == "fRoNt GaTe"
    stored = store.get_camera(added.id)
    assert stored is not None and stored.name == "fRoNt GaTe"


def test_an_injection_string_in_a_name_is_stored_as_plain_text(
    store: SqliteLibraryStore, library_path: Path
) -> None:
    added = store.add_camera(new_camera(INJECTION, location=INJECTION, department=INJECTION))
    store.add_camera(new_camera("Yard", username="x' OR '1'='1"))

    assert store.get_camera(added.id) == added
    assert [c.name for c in store.list_cameras()] == [INJECTION, "Yard"]
    other = store.get_camera(CAM_2)
    assert other is not None and other.username == "x' OR '1'='1"
    with raw_connection(library_path) as db:
        assert db.execute("SELECT count(*) FROM cameras").fetchone()[0] == 2
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


# --- Values the dataclass lets through but the library cannot hold ---------------------


def test_an_ip_over_253_characters_is_refused(store: SqliteLibraryStore) -> None:
    with pytest.raises(LibraryError, match="253"):
        store.add_camera(new_camera(ip="a" * 254))
    assert store.list_cameras() == []
    assert store.add_camera(new_camera(ip="a" * 253)).id == CAM_1  # no number was used up


@pytest.mark.parametrize(
    "fields",
    [
        {"name": " "},
        {"name": "x" * 81},
        {"ip": " "},
        {"username": ""},
        {"username": "x" * 65},
        {"status": "deleted"},
        {"location": ""},
        {"department": " "},
        {"created_at": datetime(2026, 10, 30, 9)},
    ],
    ids=lambda fields: next(iter(fields)),
)
def test_new_camera_refuses_bad_values_before_any_sql(fields: dict[str, object]) -> None:
    values: dict[str, object] = {
        "name": "Gate",
        "ip": "10.0.0.1",
        "username": "viewer",
        "status": "online",
        "location": None,
        "department": None,
        "created_at": datetime(2026, 10, 30, tzinfo=UTC),
    }
    with pytest.raises(ValueError):
        NewCamera(**{**values, **fields})  # type: ignore[arg-type]


# --- Counts ------------------------------------------------------------------------------


@pytest.fixture
def counted(store: SqliteLibraryStore) -> SqliteLibraryStore:
    """CAM-001 with 2 recordings, 3 clips (2 saved) and 2 zones; CAM-002 with 1 recording
    and 1 clip, nothing saved and no zones; CAM-003 with nothing at all."""
    for name in ("Front gate", "Yard", "Empty"):
        store.add_camera(new_camera(name))
    store.add_recording(recording("rec-1"))
    store.add_recording(recording("rec-2", day=date(2026, 10, 30)))
    store.add_recording(recording("rec-3", CAM_2))
    store.add_clip(clip("clip-1"))
    store.add_clip(clip("clip-2", start_time=time(10, 1), start_seconds=60, end_seconds=70))
    store.add_clip(clip("clip-3", "rec-2", day=date(2026, 10, 30)))
    store.add_clip(clip("clip-4", "rec-3"))
    saved_at = datetime(2026, 10, 30, 9, tzinfo=UTC)
    store.add_saved_clip("saved-1", "clip-1", "", saved_at)
    store.add_saved_clip("saved-3", "clip-3", "", saved_at)
    store.add_zone(zone("zone-1"))
    store.add_zone(zone("zone-2", name="Door"))
    return store


def test_camera_counts_cover_every_camera_including_zeros(counted: SqliteLibraryStore) -> None:
    assert counted.camera_counts() == {
        CAM_1: CameraCounts(recordings=2, zones=2, saved_clips=2),
        CAM_2: CameraCounts(recordings=1, zones=0, saved_clips=0),
        "CAM-003": CameraCounts(recordings=0, zones=0, saved_clips=0),
    }


def test_camera_counts_follow_changes(counted: SqliteLibraryStore) -> None:
    counted.delete_saved_clip("saved-1")
    counted.delete_zone("zone-2")
    counted.add_saved_clip("saved-4", "clip-4", "", datetime(2026, 10, 30, tzinfo=UTC))
    counted.delete_camera("CAM-003")

    assert counted.camera_counts() == {
        CAM_1: CameraCounts(recordings=2, zones=1, saved_clips=1),
        CAM_2: CameraCounts(recordings=1, zones=0, saved_clips=1),
    }


@pytest.fixture
def statement_log(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every SQL statement the store's connections run, in order."""
    log: list[str] = []
    real_connect = store_module.SqliteLibraryStore._connect

    def traced_connect(self: SqliteLibraryStore) -> sqlite3.Connection:
        connection = real_connect(self)
        connection.set_trace_callback(log.append)
        return connection

    monkeypatch.setattr(store_module.SqliteLibraryStore, "_connect", traced_connect)
    yield log


def test_camera_counts_run_the_same_queries_for_3_cameras_as_for_60(
    store: SqliteLibraryStore, statement_log: list[str]
) -> None:
    for n in range(1, 4):
        store.add_camera(new_camera(f"Camera {n}"))
    statement_log.clear()
    store.camera_counts()
    with_three = list(statement_log)

    for n in range(4, 61):
        store.add_camera(new_camera(f"Camera {n}"))
    statement_log.clear()
    counts = store.camera_counts()

    assert len(counts) == 60
    assert statement_log == with_three
    assert sum("SELECT" in sql for sql in with_three) == 1
