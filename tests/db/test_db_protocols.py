"""SqliteLibraryStore satisfies every library Protocol, method by method and signature by
signature, so api-agent can wire it wherever the application asks for a port."""

import inspect
from datetime import date

import pytest

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.ports.library_store import (
    ClipStore,
    RecordingStore,
    SavedClipStore,
    ZoneStore,
)

PROTOCOLS = [RecordingStore, ClipStore, ZoneStore, SavedClipStore]


def _protocol_methods(protocol: type) -> list[str]:
    return sorted(
        name
        for name, member in vars(protocol).items()
        if inspect.isfunction(member) and not name.startswith("_")
    )


def test_the_store_can_stand_in_for_each_protocol(store: SqliteLibraryStore) -> None:
    recordings: RecordingStore = store
    clips: ClipStore = store
    zones: ZoneStore = store
    saved: SavedClipStore = store
    assert recordings.list_cameras() == []
    assert clips.list_clips("cam-1", date(2026, 10, 29)) == []
    assert zones.list_zones() == []
    assert saved.list_saved_clips() == []


def test_the_protocols_have_the_methods_this_test_expects() -> None:
    assert {name for p in PROTOCOLS for name in _protocol_methods(p)} == {
        "list_cameras",
        "get_camera",
        "summarise_days",
        "list_recordings",
        "get_recording",
        "add_recording",
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


@pytest.mark.parametrize(
    ("protocol", "method"),
    [(p, name) for p in PROTOCOLS for name in _protocol_methods(p)],
    ids=lambda value: value if isinstance(value, str) else value.__name__,
)
def test_each_method_has_the_protocols_exact_signature(protocol: type, method: str) -> None:
    expected = inspect.signature(getattr(protocol, method), eval_str=True)
    actual = inspect.signature(getattr(SqliteLibraryStore, method), eval_str=True)
    assert actual == expected
