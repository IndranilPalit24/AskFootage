"""The four library stores the use cases work through, and server-side id generation.

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
    ClipStore,
    RecordingStore,
    SavedClipStore,
    ZoneStore,
)

DEFAULT_CAMERA_ID = "loading-dock"
"""The one camera v1 covers; uploads go to it when no camera is named."""

IdFactory = Callable[[str], str]
"""Makes a new id from a prefix, such as "zone" -> "zone-3f2a9c1b7d4e"."""


def new_id(prefix: str) -> str:
    """A fresh id: the prefix, a dash and 12 random hex digits (48 bits from uuid4)."""
    return f"{prefix}-{uuid4().hex[:12]}"


class LibraryStore(RecordingStore, ClipStore, ZoneStore, SavedClipStore, Protocol):
    """One object that implements all four library Protocols, as the SQLite store does."""


@dataclass(frozen=True, slots=True)
class Library:
    """The stores behind the use cases: recordings, clips, zones and saved clips."""

    recordings: RecordingStore
    clips: ClipStore
    zones: ZoneStore
    saved_clips: SavedClipStore

    @classmethod
    def from_store(cls, store: LibraryStore) -> Library:
        """A Library whose four stores are the same object."""
        return cls(recordings=store, clips=store, zones=store, saved_clips=store)


def require_camera(library: Library, camera_id: str) -> Camera:
    """The camera with this id; raises NotFoundError when there is none."""
    camera = library.recordings.get_camera(camera_id)
    if camera is None:
        raise NotFoundError("Camera not found.")
    return camera
