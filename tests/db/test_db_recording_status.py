"""A recording's status and status note: compare-and-set, notes set and cleared, refusals
that change nothing, and the note column's own constraints."""

import sqlite3
import threading
from datetime import date
from pathlib import Path

import pytest
from db_library_helpers import CAM_1, new_camera, raw_connection, recording

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.ports.library_store import STATUS_NOTE_MAX, Recording, RecordingStatus

INJECTION = "'); UPDATE recordings SET status = 'ready'; --"


@pytest.fixture
def waiting(store: SqliteLibraryStore) -> SqliteLibraryStore:
    """CAM-001 with rec-1 (waiting, no note) and rec-2 (ready, no note)."""
    store.add_camera(new_camera())
    store.add_recording(recording("rec-1", status="waiting"))
    store.add_recording(recording("rec-2", status="ready"))
    return store


def _row(path: Path, recording_id: str) -> tuple[object, ...]:
    with raw_connection(path) as db:
        return db.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()


def test_a_status_note_round_trips_through_add_and_every_read(store: SqliteLibraryStore) -> None:
    store.add_camera(new_camera())
    noted = recording("rec-9", status="waiting", status_note="The file could not be read.")
    store.add_recording(noted)

    assert store.get_recording("rec-9") == noted
    assert store.list_recordings(CAM_1, noted.day) == [noted]
    assert store.list_recordings(None, noted.day) == [noted]


def test_setting_without_expected_always_changes_and_returns_the_recording(
    waiting: SqliteLibraryStore,
) -> None:
    changed = waiting.set_recording_status("rec-2", "indexing")

    assert changed == recording("rec-2", status="indexing")
    assert waiting.get_recording("rec-2") == changed
    assert waiting.get_recording("rec-1") == recording("rec-1", status="waiting")


def test_compare_and_set_changes_when_the_status_is_the_expected_one(
    waiting: SqliteLibraryStore,
) -> None:
    changed = waiting.set_recording_status("rec-1", "preparing", expected="waiting")

    assert changed == recording("rec-1", status="preparing")
    assert waiting.get_recording("rec-1") == changed


@pytest.mark.parametrize("expected", ["preparing", "indexing", "ready"])
def test_compare_and_set_changes_nothing_when_the_status_is_another(
    waiting: SqliteLibraryStore, library_path: Path, expected: RecordingStatus
) -> None:
    waiting.set_recording_status("rec-1", "waiting", note="Try again later.")
    before = _row(library_path, "rec-1")

    assert waiting.set_recording_status("rec-1", "indexing", expected=expected) is None

    assert _row(library_path, "rec-1") == before
    assert waiting.get_recording("rec-1") == recording(
        "rec-1", status="waiting", status_note="Try again later."
    )


@pytest.mark.parametrize("expected", [None, "waiting"])
def test_an_unknown_recording_is_none(
    waiting: SqliteLibraryStore, expected: RecordingStatus | None
) -> None:
    assert waiting.set_recording_status("rec-nope", "ready", expected=expected) is None
    assert waiting.get_recording("rec-nope") is None


def test_a_note_is_set_kept_on_read_and_cleared_by_none(waiting: SqliteLibraryStore) -> None:
    failed = waiting.set_recording_status(
        "rec-1", "waiting", expected="waiting", note="Indexing stopped: the video is empty."
    )
    assert failed is not None
    assert failed.status_note == "Indexing stopped: the video is empty."
    assert waiting.list_recordings(CAM_1, date(2026, 10, 29))[0] == failed

    cleared = waiting.set_recording_status("rec-1", "preparing", expected="waiting")

    assert cleared == recording("rec-1", status="preparing")
    assert cleared is not None and cleared.status_note is None


def test_two_callers_racing_to_claim_one_recording_cannot_both_win(
    waiting: SqliteLibraryStore,
) -> None:
    barrier = threading.Barrier(8)
    results: list[Recording | None] = []
    lock = threading.Lock()

    def claim() -> None:
        barrier.wait()
        outcome = waiting.set_recording_status("rec-1", "preparing", expected="waiting")
        with lock:
            results.append(outcome)

    workers = [threading.Thread(target=claim) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert sum(result is not None for result in results) == 1
    assert waiting.get_recording("rec-1") == recording("rec-1", status="preparing")


@pytest.mark.parametrize(
    ("status", "expected", "note"),
    [
        ("finished", None, None),
        ("ready", "done", None),
        ("ready", None, ""),
        ("ready", None, "   "),
        ("ready", None, "x" * (STATUS_NOTE_MAX + 1)),
    ],
    ids=["bad-status", "bad-expected", "empty-note", "blank-note", "long-note"],
)
def test_a_value_the_recording_rules_refuse_is_a_value_error_and_changes_nothing(
    waiting: SqliteLibraryStore,
    library_path: Path,
    status: str,
    expected: str | None,
    note: str | None,
) -> None:
    before = _row(library_path, "rec-1")
    with pytest.raises(ValueError):
        waiting.set_recording_status(
            "rec-1",
            status,  # type: ignore[arg-type]
            expected=expected,  # type: ignore[arg-type]
            note=note,
        )
    assert _row(library_path, "rec-1") == before


def test_the_longest_note_and_an_injection_string_are_stored_as_text(
    waiting: SqliteLibraryStore, library_path: Path
) -> None:
    longest = "n" * STATUS_NOTE_MAX
    assert waiting.set_recording_status("rec-1", "waiting", note=longest) is not None
    assert waiting.get_recording("rec-1") == recording(
        "rec-1", status="waiting", status_note=longest
    )

    changed = waiting.set_recording_status("rec-1", "waiting", note=INJECTION)

    assert changed is not None and changed.status_note == INJECTION
    assert waiting.get_recording("rec-2") == recording("rec-2", status="ready")
    assert _row(library_path, "rec-1")[-1] == INJECTION


@pytest.mark.parametrize(
    "note", ["", "   ", "\t\n", "x" * (STATUS_NOTE_MAX + 1), b"note"], ids=repr
)
def test_the_schema_refuses_a_bad_status_note(
    waiting: SqliteLibraryStore, library_path: Path, note: object
) -> None:
    with raw_connection(library_path) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE recordings SET status_note = ? WHERE id = 'rec-1'", (note,))


def test_the_schema_accepts_no_note_and_the_longest_note(
    waiting: SqliteLibraryStore, library_path: Path
) -> None:
    with raw_connection(library_path) as db:
        db.execute("UPDATE recordings SET status_note = ? WHERE id = 'rec-1'", ("x" * 300,))
        db.execute("UPDATE recordings SET status_note = NULL WHERE id = 'rec-1'")
