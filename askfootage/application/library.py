"""The library stores the use cases work through, and server-side id generation.

Use cases depend on the Protocols in askfootage.ports.library_store, never on an adapter:
the composition root (askfootage/interfaces/api/app.py) decides which store backs them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from askfootage.application.errors import NotFoundError
from askfootage.ports.library_store import (
    Camera,
    CameraStore,
    ClipStore,
    RecordingStore,
    SavedClipStore,
    ZoneStore,
)

IdFactory = Callable[[str], str]
"""Makes a new id from a prefix, such as "zone" -> "zone-3f2a9c1b7d4e"."""

CAMERA_NOT_FOUND = "Camera not found."


def new_id(prefix: str) -> str:
    """A fresh id: the prefix, a dash and 12 random hex digits (48 bits from uuid4)."""
    return f"{prefix}-{uuid4().hex[:12]}"


class LibraryStore(CameraStore, RecordingStore, ClipStore, ZoneStore, SavedClipStore, Protocol):
    """One object that implements all five library Protocols, as the SQLite store does."""


@dataclass(frozen=True, slots=True)
class Library:
    """The stores behind the use cases: cameras, recordings, clips, zones and saved clips."""

    cameras: CameraStore
    recordings: RecordingStore
    clips: ClipStore
    zones: ZoneStore
    saved_clips: SavedClipStore

    @classmethod
    def from_store(cls, store: LibraryStore) -> Library:
        """A Library whose five stores are the same object."""
        return cls(cameras=store, recordings=store, clips=store, zones=store, saved_clips=store)


def require_camera(library: Library, camera_id: str) -> Camera:
    """The camera with this id; raises NotFoundError when there is none."""
    camera = library.cameras.get_camera(camera_id)
    if camera is None:
        raise NotFoundError(CAMERA_NOT_FOUND)
    return camera


def require_camera_filter(library: Library, camera_id: str | None) -> None:
    """Check an optional camera filter: None means every camera, an unknown id is 404.

    Raises NotFoundError when camera_id is given but no such camera exists.
    """
    if camera_id is not None:
        require_camera(library, camera_id)
