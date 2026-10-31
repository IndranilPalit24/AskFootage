"""Recordings: round trips, orderings, filters (one camera or all), day ranges, refusals."""

from datetime import date, time

import pytest
from db_library_helpers import CAM_1, CAM_2, NO_SUCH_CAMERA, new_camera, recording

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
    """CAM-001 "Front gate" and CAM-002 "Yard", no recordings."""
    assert store.add_camera(new_camera("Front gate")).id == CAM_1
    assert store.add_camera(new_camera("Yard")).id == CAM_2
    return store


def test_unknown_camera_lookups_return_empty(store: SqliteLibraryStore) -> None:
    day = date(2026, 10, 29)
    assert store.list_recordings(CAM_1, day) == []
    assert store.list_recordings(None, day) == []
    assert store.summarise_days(CAM_1, date(2026, 10, 1), date(2026, 10, 31)) == []
    assert store.summarise_days(None, date(2026, 10, 1), date(2026, 10, 31)) == []


@pytest.mark.parametrize("status", ["waiting", "preparing", "indexing", "ready"])
def test_a_recording_round_trips_exactly(
    two_cameras: SqliteLibraryStore, status: RecordingStatus
) -> None:
    saved = recording("rec-7", CAM_2, date(2026, 2, 28), time(7, 8, 9), 0, status)
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
        two_cameras.add_recording(recording(camera_id=NO_SUCH_CAMERA))
    assert two_cameras.get_recording("rec-1") is None
    assert "sqlite" not in str(refused.value).lower()


def test_library_errors_share_one_base(two_cameras: SqliteLibraryStore) -> None:
    with pytest.raises(LibraryError):
        two_cameras.add_recording(recording(camera_id=NO_SUCH_CAMERA))


def test_list_recordings_orders_by_start_then_id_and_filters(
    two_cameras: SqliteLibraryStore,
) -> None:
    day = date(2026, 10, 29)
    for item in [
        recording("rec-c", start_time=time(23, 59, 59)),
        recording("rec-b", start_time=time(8)),
        recording("rec-a", start_time=time(8)),  # same start: id breaks the tie
        recording("rec-z", start_time=time(0)),
        recording("rec-other-camera", camera_id=CAM_2, start_time=time(9)),
        recording("rec-day-before", day=date(2026, 10, 28)),
        recording("rec-day-after", day=date(2026, 10, 30)),
    ]:
        two_cameras.add_recording(item)

    listed = two_cameras.list_recordings(CAM_1, day)

    assert [item.id for item in listed] == ["rec-z", "rec-a", "rec-b", "rec-c"]
    assert listed[0] == recording("rec-z", start_time=time(0))
    assert [item.id for item in two_cameras.list_recordings(CAM_2, day)] == ["rec-other-camera"]


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
        recording("rec-cam-2", camera_id=CAM_2, day=date(2026, 10, 25)),
    ]:
        two_cameras.add_recording(item)

    assert two_cameras.summarise_days(CAM_1, first, last) == [
        DaySummary(day=first, recordings=2, ready=1),
        DaySummary(day=date(2026, 10, 27), recordings=1, ready=0),
        DaySummary(day=last, recordings=2, ready=2),
    ]


def test_summarise_days_of_one_day_and_of_a_reversed_range(
    two_cameras: SqliteLibraryStore,
) -> None:
    day = date(2026, 10, 29)
    two_cameras.add_recording(recording(day=day))

    assert two_cameras.summarise_days(CAM_1, day, day) == [DaySummary(day, 1, 1)]
    assert two_cameras.summarise_days(CAM_1, day, date(2026, 10, 28)) == []


def test_summarise_days_across_a_month_and_year_end(two_cameras: SqliteLibraryStore) -> None:
    for index, day in enumerate([date(2026, 12, 31), date(2027, 1, 1), date(2027, 2, 1)]):
        two_cameras.add_recording(recording(f"rec-{index}", day=day))

    summary = two_cameras.summarise_days(CAM_1, date(2026, 12, 31), date(2027, 1, 31))

    assert [item.day for item in summary] == [date(2026, 12, 31), date(2027, 1, 1)]


# --- Every camera at once (camera_id None) --------------------------------------------


@pytest.fixture
def three_cameras_of_recordings(two_cameras: SqliteLibraryStore) -> SqliteLibraryStore:
    """Recordings on CAM-001, CAM-002 and CAM-003 around 29 Oct, with tied start times."""
    assert two_cameras.add_camera(new_camera("Back door")).id == "CAM-003"
    for item in [
        recording("rec-z", CAM_1, start_time=time(0)),
        recording("rec-b", CAM_1, start_time=time(8)),
        recording("rec-a", "CAM-003", start_time=time(8)),  # tie: camera before id
        recording("rec-c", CAM_2, start_time=time(8)),
        recording("rec-d", CAM_2, start_time=time(8)),  # tie on one camera: id
        recording("rec-late", "CAM-003", start_time=time(23, 59, 59), status="indexing"),
        recording("rec-before", CAM_2, day=date(2026, 10, 28), status="waiting"),
        recording("rec-after", "CAM-003", day=date(2026, 10, 30)),
    ]:
        two_cameras.add_recording(item)
    return two_cameras


def test_list_recordings_for_every_camera_orders_by_start_then_camera_then_id(
    three_cameras_of_recordings: SqliteLibraryStore,
) -> None:
    listed = three_cameras_of_recordings.list_recordings(None, date(2026, 10, 29))

    assert [(r.id, r.camera) for r in listed] == [
        ("rec-z", CAM_1),
        ("rec-b", CAM_1),
        ("rec-c", CAM_2),
        ("rec-d", CAM_2),
        ("rec-a", "CAM-003"),
        ("rec-late", "CAM-003"),
    ]
    assert listed[0] == recording("rec-z", CAM_1, start_time=time(0))


def test_list_recordings_for_one_camera_is_that_cameras_slice_of_all(
    three_cameras_of_recordings: SqliteLibraryStore,
) -> None:
    day = date(2026, 10, 29)
    everything = three_cameras_of_recordings.list_recordings(None, day)
    for camera_id in (CAM_1, CAM_2, "CAM-003"):
        one = three_cameras_of_recordings.list_recordings(camera_id, day)
        assert one == [r for r in everything if r.camera == camera_id], camera_id


def test_summarise_days_for_every_camera_adds_the_cameras_together(
    three_cameras_of_recordings: SqliteLibraryStore,
) -> None:
    first, last = date(2026, 10, 28), date(2026, 10, 30)

    assert three_cameras_of_recordings.summarise_days(None, first, last) == [
        DaySummary(day=date(2026, 10, 28), recordings=1, ready=0),
        DaySummary(day=date(2026, 10, 29), recordings=6, ready=5),
        DaySummary(day=date(2026, 10, 30), recordings=1, ready=1),
    ]
    assert three_cameras_of_recordings.summarise_days(CAM_2, first, last) == [
        DaySummary(day=date(2026, 10, 28), recordings=1, ready=0),
        DaySummary(day=date(2026, 10, 29), recordings=2, ready=2),
    ]
    # The range edges are inclusive for every camera too.
    day = date(2026, 10, 29)
    assert three_cameras_of_recordings.summarise_days(None, day, day) == [
        DaySummary(day=day, recordings=6, ready=5)
    ]
    assert three_cameras_of_recordings.summarise_days(None, last, first) == []


def test_a_deleted_camera_drops_out_of_the_all_camera_views(
    three_cameras_of_recordings: SqliteLibraryStore,
) -> None:
    assert three_cameras_of_recordings.delete_camera("CAM-003") is True

    listed = three_cameras_of_recordings.list_recordings(None, date(2026, 10, 29))

    assert {r.camera for r in listed} == {CAM_1, CAM_2}
    assert three_cameras_of_recordings.summarise_days(
        None, date(2026, 10, 28), date(2026, 10, 30)
    ) == [
        DaySummary(day=date(2026, 10, 28), recordings=1, ready=0),
        DaySummary(day=date(2026, 10, 29), recordings=4, ready=4),
    ]
