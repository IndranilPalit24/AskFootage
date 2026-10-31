"""SqliteLibraryStore satisfies every library Protocol, and SqliteTrackStore the TrackStore
Protocol, method by method and signature by signature, so the application layer can wire
them wherever it asks for a port."""

import inspect
from datetime import date

import pytest

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.adapters.sqlite.tracks import SqliteTrackStore
from askfootage.ports.library_store import (
    CameraStore,
    ClipStore,
    RecordingStore,
    SavedClipStore,
    ZoneStore,
)
from askfootage.ports.track_store import TrackStore

PROTOCOLS = [CameraStore, RecordingStore, ClipStore, ZoneStore, SavedClipStore]

# Each Protocol and the class that implements it.
IMPLEMENTATIONS: list[tuple[type, type]] = [
    *((protocol, SqliteLibraryStore) for protocol in PROTOCOLS),
    (TrackStore, SqliteTrackStore),
]


def _protocol_methods(protocol: type) -> list[str]:
    return sorted(
        name
        for name, member in vars(protocol).items()
        if inspect.isfunction(member) and not name.startswith("_")
    )


def test_the_store_can_stand_in_for_each_protocol(store: SqliteLibraryStore) -> None:
    cameras: CameraStore = store
    recordings: RecordingStore = store
    clips: ClipStore = store
    zones: ZoneStore = store
    saved: SavedClipStore = store
    tracks: TrackStore = SqliteTrackStore(store)
    assert cameras.list_cameras() == []
    assert recordings.list_recordings(None, date(2026, 10, 29)) == []
    assert recordings.set_recording_status("rec-1", "ready") is None
    assert clips.list_clips(None, date(2026, 10, 29)) == []
    assert zones.list_zones() == []
    assert saved.list_saved_clips() == []
    assert tracks.tracks_for("rec-1", "person") == []


def test_the_protocols_have_the_methods_this_test_expects() -> None:
    assert {name for p in PROTOCOLS for name in _protocol_methods(p)} == {
        "list_cameras",
        "get_camera",
        "add_camera",
        "set_camera_status",
        "delete_camera",
        "camera_counts",
        "summarise_days",
        "list_recordings",
        "get_recording",
        "add_recording",
        "set_recording_status",
        "list_clips",
        "get_clip",
        "add_clip",
        "list_zones",
        "get_zone",
        "add_zone",
        "replace_zone",
        "delete_zone",
        "list_saved_clips",
        "get_saved_clip",
        "add_saved_clip",
        "update_note",
        "delete_saved_clip",
    }
    assert _protocol_methods(TrackStore) == ["delete_video", "save_tracks", "tracks_for"]


@pytest.mark.parametrize(
    ("protocol", "implementation", "method"),
    [(p, impl, name) for p, impl in IMPLEMENTATIONS for name in _protocol_methods(p)],
    ids=lambda value: value if isinstance(value, str) else value.__name__,
)
def test_each_method_has_the_protocols_exact_signature(
    protocol: type, implementation: type, method: str
) -> None:
    expected = inspect.signature(getattr(protocol, method), eval_str=True)
    actual = inspect.signature(getattr(implementation, method), eval_str=True)
    assert actual == expected
