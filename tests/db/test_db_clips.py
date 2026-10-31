"""Clips: exact round trips (evidence and key-frame order, None fields), order, filters."""

from datetime import date, time

import pytest
from db_library_helpers import CAM_1, CAM_2, NO_SUCH_CAMERA, clip, new_camera, recording

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.ports.library_store import (
    DuplicateError,
    Evidence,
    KeyFrame,
    LibraryError,
    MissingReferenceError,
)


def test_a_clip_round_trips_exactly_keeping_evidence_and_key_frame_order(
    stocked_store: SqliteLibraryStore,
) -> None:
    saved = clip(
        "clip-order",
        evidence=(
            Evidence("in_zone", "In Gate · 9 s"),
            Evidence("carrying", "Carrying · 12 s"),
            Evidence("dwell", "Stayed · 1 min"),
            Evidence("carrying", "Carrying again · 3 s"),
        ),
        key_frames=(KeyFrame(18, "b.jpg"), KeyFrame(5), KeyFrame(12, "a.jpg"), KeyFrame(5)),
        thumbnail_url="thumbs/clip-order.jpg",
    )
    stocked_store.add_clip(saved)

    assert stocked_store.get_clip("clip-order") == saved


def test_none_and_empty_fields_round_trip(stocked_store: SqliteLibraryStore) -> None:
    bare = clip("clip-bare", evidence=(), key_frames=(), zone=None, thumbnail_url=None)
    stocked_store.add_clip(bare)

    got = stocked_store.get_clip("clip-bare")

    assert got == bare
    assert got is not None and got.zone is None and got.thumbnail_url is None
    assert got.evidence == () and got.key_frames == ()


def test_unicode_text_round_trips(stocked_store: SqliteLibraryStore) -> None:
    fancy = clip("clip-unicode", label="Person · carrying a 📦 — “quoted”", zone="Zone ü")
    stocked_store.add_clip(fancy)
    assert stocked_store.get_clip("clip-unicode") == fancy


def test_get_clip_of_unknown_id_is_none(stocked_store: SqliteLibraryStore) -> None:
    assert stocked_store.get_clip("clip-nope") is None


def test_add_clip_refuses_a_taken_id(stocked_store: SqliteLibraryStore) -> None:
    with pytest.raises(DuplicateError):
        stocked_store.add_clip(clip(label="Something else"))
    assert stocked_store.get_clip("clip-1") == clip()


def test_add_clip_refuses_an_unknown_recording(stocked_store: SqliteLibraryStore) -> None:
    with pytest.raises(MissingReferenceError):
        stocked_store.add_clip(clip("clip-2", recording_id="rec-nope"))
    assert stocked_store.get_clip("clip-2") is None


def test_add_clip_refuses_a_day_that_is_not_its_recordings(
    stocked_store: SqliteLibraryStore,
) -> None:
    with pytest.raises(LibraryError, match="day") as refused:
        stocked_store.add_clip(clip("clip-2", day=date(2026, 10, 30)))
    assert not isinstance(refused.value, DuplicateError | MissingReferenceError)
    assert stocked_store.get_clip("clip-2") is None


@pytest.fixture
def two_camera_clips(stocked_store: SqliteLibraryStore) -> SqliteLibraryStore:
    """clip-1 plus clips on both cameras, on 29 and 30 Oct, with tied start times."""
    assert stocked_store.add_camera(new_camera("Yard")).id == CAM_2
    stocked_store.add_recording(recording("rec-2", start_time=time(0)))
    stocked_store.add_recording(recording("rec-cam-2", camera_id=CAM_2))
    stocked_store.add_recording(recording("rec-next-day", day=date(2026, 10, 30)))
    for item in [
        clip("clip-late", start_time=time(23, 59, 59), start_seconds=6000, end_seconds=6001),
        clip("clip-b", "rec-2", start_time=time(10, 0, 5)),  # same start as clip-1
        clip("clip-a", "rec-2", start_time=time(10, 0, 5)),
        clip("clip-midnight", "rec-2", start_time=time(0), start_seconds=0, end_seconds=1),
        clip("clip-cam-2", "rec-cam-2"),  # same start as clip-1, on the other camera
        clip("clip-next-day", "rec-next-day", day=date(2026, 10, 30)),
    ]:
        stocked_store.add_clip(item)
    return stocked_store


def test_list_clips_orders_by_start_time_then_id_and_filters(
    two_camera_clips: SqliteLibraryStore,
) -> None:
    day = date(2026, 10, 29)

    listed = two_camera_clips.list_clips(CAM_1, day)

    assert [item.id for item in listed] == [
        "clip-midnight",
        "clip-1",
        "clip-a",
        "clip-b",
        "clip-late",
    ]
    assert listed[1] == clip()  # evidence and key frames come back in bulk lists too
    assert [item.id for item in two_camera_clips.list_clips(CAM_2, day)] == ["clip-cam-2"]
    assert [c.id for c in two_camera_clips.list_clips(CAM_1, date(2026, 10, 30))] == [
        "clip-next-day"
    ]
    assert two_camera_clips.list_clips(NO_SUCH_CAMERA, day) == []


def test_list_clips_for_every_camera_merges_them_by_start_time_then_id(
    two_camera_clips: SqliteLibraryStore,
) -> None:
    listed = two_camera_clips.list_clips(None, date(2026, 10, 29))

    assert [item.id for item in listed] == [
        "clip-midnight",
        "clip-1",
        "clip-a",
        "clip-b",
        "clip-cam-2",
        "clip-late",
    ]
    assert listed[1] == clip()
    assert [c.id for c in two_camera_clips.list_clips(None, date(2026, 10, 30))] == [
        "clip-next-day"
    ]
    assert two_camera_clips.list_clips(None, date(2026, 10, 28)) == []


def test_list_clips_keeps_each_clips_own_evidence(stocked_store: SqliteLibraryStore) -> None:
    first = clip("clip-x", evidence=(Evidence("dwell", "X1"),), key_frames=(KeyFrame(7),))
    second = clip(
        "clip-y",
        evidence=(Evidence("in_zone", "Y1"), Evidence("carrying", "Y2")),
        key_frames=(),
    )
    stocked_store.add_clip(first)
    stocked_store.add_clip(second)

    by_id = {item.id: item for item in stocked_store.list_clips(CAM_1, date(2026, 10, 29))}

    assert by_id["clip-x"] == first
    assert by_id["clip-y"] == second
