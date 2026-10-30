"""Saved clips: aware UTC timestamps, newest-first order, day filter, notes, refusals."""

from datetime import UTC, date, datetime, time, timedelta, timezone

import pytest
from db_library_helpers import clip, recording

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.ports.library_store import DuplicateError, MissingReferenceError, SavedClip

SAVED_AT = datetime(2026, 10, 30, 9, 12, 44, tzinfo=UTC)


def test_add_saved_clip_returns_what_get_returns(stocked_store: SqliteLibraryStore) -> None:
    returned = stocked_store.add_saved_clip("saved-1", "clip-1", "Check the paperwork", SAVED_AT)

    assert returned == SavedClip("saved-1", clip(), "Check the paperwork", SAVED_AT)
    assert stocked_store.get_saved_clip("saved-1") == returned


def test_saved_at_comes_back_aware_in_utc_with_microseconds(
    stocked_store: SqliteLibraryStore,
) -> None:
    india = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 10, 30, 14, 42, 44, 123456, tzinfo=india)

    stocked_store.add_saved_clip("saved-1", "clip-1", "", local)
    got = stocked_store.get_saved_clip("saved-1")

    assert got is not None
    assert got.saved_at == local
    assert got.saved_at.utcoffset() == timedelta(0)
    assert got.saved_at == datetime(2026, 10, 30, 9, 12, 44, 123456, tzinfo=UTC)


def test_a_naive_saved_at_is_refused(stocked_store: SqliteLibraryStore) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        stocked_store.add_saved_clip("saved-1", "clip-1", "", datetime(2026, 10, 30, 9))
    assert stocked_store.list_saved_clips() == []


def test_add_saved_clip_refusals(stocked_store: SqliteLibraryStore) -> None:
    stocked_store.add_clip(clip("clip-2", start_time=time(10, 1), start_seconds=60, end_seconds=70))
    stocked_store.add_saved_clip("saved-1", "clip-1", "first", SAVED_AT)

    with pytest.raises(MissingReferenceError):
        stocked_store.add_saved_clip("saved-2", "clip-nope", "", SAVED_AT)
    with pytest.raises(DuplicateError, match="id"):
        stocked_store.add_saved_clip("saved-1", "clip-2", "", SAVED_AT)
    with pytest.raises(DuplicateError, match="already saved"):
        stocked_store.add_saved_clip("saved-3", "clip-1", "", SAVED_AT)

    assert [s.id for s in stocked_store.list_saved_clips()] == ["saved-1"]


def test_unknown_saved_clip_lookups(stocked_store: SqliteLibraryStore) -> None:
    assert stocked_store.get_saved_clip("saved-nope") is None
    assert stocked_store.update_note("saved-nope", "hello") is None
    assert stocked_store.delete_saved_clip("saved-nope") is False
    assert stocked_store.list_saved_clips() == []
    assert stocked_store.list_saved_clips(date(2026, 10, 29)) == []


def test_update_note_returns_the_saved_clip_after_the_change(
    stocked_store: SqliteLibraryStore,
) -> None:
    stocked_store.add_saved_clip("saved-1", "clip-1", "old", SAVED_AT)

    updated = stocked_store.update_note("saved-1", "x" * 500)

    assert updated == SavedClip("saved-1", clip(), "x" * 500, SAVED_AT)
    assert stocked_store.get_saved_clip("saved-1") == updated
    assert stocked_store.update_note("saved-1", "") == SavedClip("saved-1", clip(), "", SAVED_AT)


def test_delete_saved_clip_keeps_the_clip(stocked_store: SqliteLibraryStore) -> None:
    stocked_store.add_saved_clip("saved-1", "clip-1", "", SAVED_AT)

    assert stocked_store.delete_saved_clip("saved-1") is True
    assert stocked_store.delete_saved_clip("saved-1") is False

    assert stocked_store.get_saved_clip("saved-1") is None
    assert stocked_store.get_clip("clip-1") == clip()
    # ...and the clip can be saved again afterwards.
    stocked_store.add_saved_clip("saved-2", "clip-1", "", SAVED_AT)


def test_list_saved_clips_newest_first_then_id_and_by_clip_day(
    stocked_store: SqliteLibraryStore,
) -> None:
    stocked_store.add_recording(recording("rec-2", day=date(2026, 10, 30)))
    for index in range(2, 6):
        stocked_store.add_clip(
            clip(
                f"clip-{index}",
                start_time=time(10, index),
                start_seconds=60 * index,
                end_seconds=60 * index + 5,
            )
        )
    stocked_store.add_clip(clip("clip-30", "rec-2", day=date(2026, 10, 30)))
    stocked_store.add_saved_clip("saved-old", "clip-1", "", SAVED_AT - timedelta(days=1))
    stocked_store.add_saved_clip("saved-b", "clip-2", "", SAVED_AT)  # same moment: id order
    stocked_store.add_saved_clip("saved-a", "clip-3", "", SAVED_AT)
    stocked_store.add_saved_clip("saved-new", "clip-30", "", SAVED_AT + timedelta(microseconds=1))
    stocked_store.add_saved_clip("saved-tiny", "clip-4", "", SAVED_AT - timedelta(microseconds=1))

    assert [s.id for s in stocked_store.list_saved_clips()] == [
        "saved-new",
        "saved-a",
        "saved-b",
        "saved-tiny",
        "saved-old",
    ]
    assert [s.id for s in stocked_store.list_saved_clips(date(2026, 10, 29))] == [
        "saved-a",
        "saved-b",
        "saved-tiny",
        "saved-old",
    ]
    assert [s.id for s in stocked_store.list_saved_clips(date(2026, 10, 30))] == ["saved-new"]
    assert stocked_store.list_saved_clips(date(2026, 10, 28)) == []


def test_saved_at_order_survives_different_time_zones(stocked_store: SqliteLibraryStore) -> None:
    """Stored as UTC text of fixed width, so text order is the true time order."""
    stocked_store.add_clip(clip("clip-2", start_time=time(10, 1), start_seconds=60, end_seconds=70))
    later_in_new_york = datetime(2026, 10, 30, 20, 0, tzinfo=timezone(timedelta(hours=-4)))
    earlier_in_tokyo = datetime(2026, 10, 30, 23, 0, tzinfo=timezone(timedelta(hours=9)))
    # 31 Oct 00:00 UTC and 30 Oct 14:00 UTC: by local clock text Tokyo's "23:00" would
    # sort after New York's "20:00", but New York's is the later moment.
    stocked_store.add_saved_clip("saved-tokyo", "clip-2", "", earlier_in_tokyo)
    stocked_store.add_saved_clip("saved-ny", "clip-1", "", later_in_new_york)

    assert [s.id for s in stocked_store.list_saved_clips()] == ["saved-ny", "saved-tokyo"]
