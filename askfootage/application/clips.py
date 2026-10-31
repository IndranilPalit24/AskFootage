"""A clip together with the id of the camera that recorded it.

The ports' Clip carries no camera: a clip's camera is its recording's camera, and its day
is its recording's day. These helpers find the cameras with as few store calls as they
can: one get_recording call for a single clip, and one list_recordings call per distinct
day for a list of clips, never one call per clip.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from askfootage.application.library import Library
from askfootage.ports.library_store import Clip, SavedClip


@dataclass(frozen=True, slots=True)
class ClipWithCamera:
    """A clip and the id of the camera that made its recording."""

    clip: Clip
    camera: str


@dataclass(frozen=True, slots=True)
class SavedClipWithCamera:
    """A saved clip and the id of the camera that made its clip's recording."""

    saved: SavedClip
    camera: str


def camera_of_clip(library: Library, clip: Clip) -> str | None:
    """The id of the camera that recorded the clip, or None if its recording is gone."""
    recording = library.recordings.get_recording(clip.recording_id)
    return None if recording is None else recording.camera


def cameras_of_recordings(library: Library, days: Iterable[date]) -> dict[str, str]:
    """Recording id -> camera id for every recording on the given days, all cameras.

    One list_recordings call per distinct day.
    """
    cameras: dict[str, str] = {}
    for day in sorted(set(days)):
        for recording in library.recordings.list_recordings(None, day):
            cameras[recording.id] = recording.camera
    return cameras
