"""Use cases for cameras, days, recordings, uploads, footage files and single clips."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path
from typing import Protocol

from askfootage.application.errors import NotFoundError
from askfootage.application.library import (
    DEFAULT_CAMERA_ID,
    IdFactory,
    Library,
    new_id,
    require_camera,
)
from askfootage.ports.library_store import (
    Camera,
    Clip,
    DaySummary,
    MissingReferenceError,
    Recording,
)

DAYS_SHOWN = 7
"""How many days the day picker covers, ending today."""


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    """Whether the app serves demo data, and the camera it covers."""

    demo_mode: bool
    camera: Camera


def get_status(library: Library) -> ServiceStatus:
    """The app's status.

    demo_mode is always True in v1: the only data source is the seeded demo dataset, and
    uploads are checked and registered but never processed.
    """
    camera = library.recordings.get_camera(DEFAULT_CAMERA_ID)
    if camera is None:
        cameras = library.recordings.list_cameras()
        if not cameras:
            # A library without any camera is a broken installation, not a client error.
            raise RuntimeError("the library has no cameras")
        camera = cameras[0]
    return ServiceStatus(demo_mode=True, camera=camera)


def list_days(library: Library, camera_id: str, today: date) -> list[DaySummary]:
    """Recording counts for the 7 days ending today, oldest first, with empty days as zeros.

    Raises NotFoundError for an unknown camera.
    """
    require_camera(library, camera_id)
    first_day = today - timedelta(days=DAYS_SHOWN - 1)
    found = {
        summary.day: summary
        for summary in library.recordings.summarise_days(camera_id, first_day, today)
    }
    days = (first_day + timedelta(days=offset) for offset in range(DAYS_SHOWN))
    return [found.get(day) or DaySummary(day=day, recordings=0, ready=0) for day in days]


def list_recordings(library: Library, camera_id: str, day: date) -> list[Recording]:
    """One camera's recordings on one day, ordered by start time, then id.

    Raises NotFoundError for an unknown camera.
    """
    require_camera(library, camera_id)
    recordings = library.recordings.list_recordings(camera_id, day)
    return sorted(recordings, key=lambda recording: (recording.start_time, recording.id))


def register_upload(
    library: Library, camera_id: str, day: date, *, make_id: IdFactory = new_id
) -> Recording:
    """Register an uploaded video as a new recording that waits to be processed.

    The caller has already checked the file. The recording starts at 00:00:00 with length
    0; processing fills those in later (not in v1). Raises NotFoundError for an unknown
    camera.
    """
    require_camera(library, camera_id)
    recording = Recording(
        id=make_id("rec"),
        camera=camera_id,
        day=day,
        start_time=time(0, 0, 0),
        length_seconds=0,
        status="waiting",
    )
    try:
        library.recordings.add_recording(recording)
    except MissingReferenceError:
        raise NotFoundError("Camera not found.") from None
    return recording


class FootageSource(Protocol):
    """Finds the video file that holds a recording's footage."""

    def footage_for(self, recording: Recording) -> Path | None:
        """The footage file of this recording, or None when no file is attached."""
        ...


def find_footage(library: Library, footage: FootageSource, recording_id: str) -> Path:
    """The footage file of a known recording.

    Raises NotFoundError when the recording is unknown or has no footage file.
    """
    recording = library.recordings.get_recording(recording_id)
    if recording is None:
        raise NotFoundError("Recording not found.")
    path = footage.footage_for(recording)
    if path is None:
        raise NotFoundError("Footage file not attached.")
    return path


def get_clip(library: Library, clip_id: str) -> Clip:
    """One clip with its evidence; raises NotFoundError when there is no such clip."""
    clip = library.clips.get_clip(clip_id)
    if clip is None:
        raise NotFoundError("Clip not found.")
    return clip
