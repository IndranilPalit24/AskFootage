"""Cameras and recordings: round trips, orderings, filters, day ranges and refusals."""

from datetime import date, time

import pytest
from db_library_helpers import camera, recording

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.ports.library_store import (
    DaySummary,
    DuplicateError,
    LibraryError,
    MissingReferenceError,
    RecordingStatus,
)


@pytest.fixture
def two_cameras(store: SqliteLibraryStore) -> SqliteLibraryStore:
    store.add_camera(camera("cam-2", "Yard"))
    store.add_camera(camera("cam-1", "Front gate"))
    return store


def test_cameras_round_trip_ordered_by_id(two_cameras: SqliteLibraryStore) -> None:
    assert two_cameras.list_cameras() == [camera("cam-1", "Front gate"), camera("cam-2", "Yard")]
    assert two_cameras.get_camera("cam-2") == camera("cam-2", "Yard")


def test_unknown_camera_lookups_return_none_or_empty(store: SqliteLibraryStore) -> None:
    assert store.list_cameras() == []
    assert store.get_camera("cam-1") is None
    assert store.list_recordings("cam-1", date(2026, 10, 29)) == []
    assert store.summarise_days("cam-1", date(2026, 10, 1), date(2026, 10, 31)) == []


def test_a_camera_id_can_be_added_once(two_cameras: SqliteLibraryStore) -> None:
    with pytest.raises(DuplicateError):
        two_cameras.add_camera(camera("cam-1", "Another name"))
    assert two_cameras.get_camera("cam-1") == camera("cam-1", "Front gate")


@pytest.mark.parametrize("status", ["waiting", "preparing", "indexing", "ready"])
def test_a_recording_round_trips_exactly(
    two_cameras: SqliteLibraryStore, status: RecordingStatus
) -> None:
    saved = recording("rec-7", "cam-2", date(2026, 2, 28), time(7, 8, 9), 0, status)
    two_cameras.add_recording(saved)
    assert two_cameras.get_recording("rec-7") == saved


@pytest.mark.parametrize(
    "start", [time(0, 0, 0), time(23, 59, 59)], ids=["midnight", "last-second"]
)
def test_time_of_day_edges_round_trip(two_cameras: SqliteLibraryStore, start: time) -> None:
    two_cameras.add_recording(recording("rec-edge", start_time=start))
    assert two_cameras.get_recording("rec-edge") == recording("rec-edge", start_time=start)


def test_get_recording_of_unknown_id_is_none(two_cameras: SqliteLibraryStore) -> None:
    assert two_cameras.get_recording("rec-nope") is None


def test_add_recording_refuses_a_taken_id(two_cameras: SqliteLibraryStore) -> None:
    two_cameras.add_recording(recording())
    with pytest.raises(DuplicateError):
        two_cameras.add_recording(recording(length_seconds=1))
    assert two_cameras.get_recording("rec-1") == recording()


def test_add_recording_refuses_an_unknown_camera(two_cameras: SqliteLibraryStore) -> None:
    with pytest.raises(MissingReferenceError) as refused:
        two_cameras.add_recording(recording(camera_id="cam-9"))
    assert two_cameras.get_recording("rec-1") is None
    assert "sqlite" not in str(refused.value).lower()


def test_library_errors_share_one_base(two_cameras: SqliteLibraryStore) -> None:
    with pytest.raises(LibraryError):
        two_cameras.add_recording(recording(camera_id="cam-9"))


def test_list_recordings_orders_by_start_then_id_and_filters(
    two_cameras: SqliteLibraryStore,
) -> None:
    day = date(2026, 10, 29)
    for item in [
        recording("rec-c", start_time=time(23, 59, 59)),
        recording("rec-b", start_time=time(8)),
        recording("rec-a", start_time=time(8)),  # same start: id breaks the tie
        recording("rec-z", start_time=time(0)),
        recording("rec-other-camera", camera_id="cam-2", start_time=time(9)),
        recording("rec-day-before", day=date(2026, 10, 28)),
        recording("rec-day-after", day=date(2026, 10, 30)),
    ]:
        two_cameras.add_recording(item)

    listed = two_cameras.list_recordings("cam-1", day)

    assert [item.id for item in listed] == ["rec-z", "rec-a", "rec-b", "rec-c"]
    assert listed[0] == recording("rec-z", start_time=time(0))
    assert [item.id for item in two_cameras.list_recordings("cam-2", day)] == ["rec-other-camera"]


def test_summarise_days_counts_inclusive_range_and_omits_empty_days(
    two_cameras: SqliteLibraryStore,
) -> None:
    first, last = date(2026, 10, 24), date(2026, 10, 30)
    for item in [
        recording("rec-before", day=date(2026, 10, 23)),  # one day before the range
        recording("rec-first-1", day=first, status="ready"),
        recording("rec-first-2", day=first, status="indexing"),
        recording("rec-mid", day=date(2026, 10, 27), status="waiting"),
        recording("rec-last-1", day=last, status="ready"),
        recording("rec-last-2", day=last, status="ready", start_time=time(23, 59, 59)),
        recording("rec-after", day=date(2026, 10, 31)),  # one day after the range
        recording("rec-cam-2", camera_id="cam-2", day=date(2026, 10, 25)),
    ]:
        two_cameras.add_recording(item)

    assert two_cameras.summarise_days("cam-1", first, last) == [
        DaySummary(day=first, recordings=2, ready=1),
        DaySummary(day=date(2026, 10, 27), recordings=1, ready=0),
        DaySummary(day=last, recordings=2, ready=2),
    ]


def test_summarise_days_of_one_day_and_of_a_reversed_range(
    two_cameras: SqliteLibraryStore,
) -> None:
    day = date(2026, 10, 29)
    two_cameras.add_recording(recording(day=day))

    assert two_cameras.summarise_days("cam-1", day, day) == [DaySummary(day, 1, 1)]
    assert two_cameras.summarise_days("cam-1", day, date(2026, 10, 28)) == []


def test_summarise_days_across_a_month_and_year_end(two_cameras: SqliteLibraryStore) -> None:
    for index, day in enumerate([date(2026, 12, 31), date(2027, 1, 1), date(2027, 2, 1)]):
        two_cameras.add_recording(recording(f"rec-{index}", day=day))

    summary = two_cameras.summarise_days("cam-1", date(2026, 12, 31), date(2027, 1, 31))

    assert [item.day for item in summary] == [date(2026, 12, 31), date(2027, 1, 1)]
