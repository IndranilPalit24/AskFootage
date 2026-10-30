"""Ports for the footage library: cameras, recordings, clips, zones and saved clips.

The application layer depends on the Protocols here; askfootage/adapters/sqlite implements
them, and tests use in-memory fakes. Standard library only, so no framework leaks in.

Conventions every store follows:
- Ids are chosen by the caller and stored as given: 1 to 64 letters, digits, "-" or "_".
- A lookup that finds nothing returns None (get_*) or False (replace_*, delete_*);
  it never raises. Lists come back in a fixed order, documented on each method.
- A write that would break uniqueness raises DuplicateError; one that points at a row
  that does not exist raises MissingReferenceError. Both subclass LibraryError.
- Times of day are camera-local wall-clock times; offsets inside a recording are whole
  seconds from its start. Saved-at timestamps are timezone-aware UTC datetimes.
- No identity of any kind is stored (ADR 0008): labels are neutral, such as "person".
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal, Protocol

RecordingStatus = Literal["waiting", "preparing", "indexing", "ready"]
"""waiting: not started; preparing: making the working copy; indexing: finding objects;
ready: searchable."""

EvidenceKind = Literal["carrying", "in_zone", "dwell"]
"""What a piece of evidence measured: an object carried, time inside a zone, or staying put."""

ZonePoint = tuple[float, float]
"""(x, y) as fractions of the frame's width and height, measured from the top-left corner."""

RECORDING_STATUSES: tuple[RecordingStatus, ...] = ("waiting", "preparing", "indexing", "ready")
EVIDENCE_KINDS: tuple[EvidenceKind, ...] = ("carrying", "in_zone", "dwell")

_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


class LibraryError(Exception):
    """A library store refused a write; the message is safe to show and holds no paths."""


class DuplicateError(LibraryError):
    """The write would repeat an id or another value that must be unique."""


class MissingReferenceError(LibraryError):
    """The write points at a camera, recording or clip that does not exist."""


def _check_id(kind: str, value: str) -> None:
    if not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"{kind} must be 1 to 64 letters, digits, '-' or '_'")


@dataclass(frozen=True, slots=True)
class Camera:
    """A fixed camera whose footage the library holds."""

    id: str
    name: str

    def __post_init__(self) -> None:
        _check_id("camera id", self.id)
        if not self.name.strip():
            raise ValueError("camera name must not be blank")


@dataclass(frozen=True, slots=True)
class DaySummary:
    """How many recordings one camera made on one day, and how many are ready to search."""

    day: date
    recordings: int
    ready: int

    def __post_init__(self) -> None:
        if not 0 <= self.ready <= self.recordings:
            raise ValueError("ready must be between 0 and the number of recordings")


@dataclass(frozen=True, slots=True)
class Recording:
    """One continuous video from one camera, starting at a wall-clock time on a day."""

    id: str
    camera: str
    day: date
    start_time: time
    length_seconds: int
    status: RecordingStatus

    def __post_init__(self) -> None:
        _check_id("recording id", self.id)
        _check_id("camera id", self.camera)
        if self.length_seconds < 0:
            raise ValueError("length_seconds must not be negative")
        if self.status not in RECORDING_STATUSES:
            raise ValueError(f"status must be one of {', '.join(RECORDING_STATUSES)}")


@dataclass(frozen=True, slots=True)
class Evidence:
    """One measured reason a clip matched, with its short display text."""

    kind: EvidenceKind
    text: str

    def __post_init__(self) -> None:
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError(f"evidence kind must be one of {', '.join(EVIDENCE_KINDS)}")
        if not self.text.strip():
            raise ValueError("evidence text must not be blank")


@dataclass(frozen=True, slots=True)
class KeyFrame:
    """A frame worth looking at inside a clip, at whole seconds from the recording's start."""

    at_seconds: int
    image_url: str | None = None

    def __post_init__(self) -> None:
        if self.at_seconds < 0:
            raise ValueError("at_seconds must not be negative")


@dataclass(frozen=True, slots=True)
class Clip:
    """A stretch of one recording that answers a question, with the evidence for it.

    start_seconds and end_seconds are offsets inside the recording; start_time is the
    wall-clock time at start_seconds; day is the recording's day.
    """

    id: str
    recording_id: str
    day: date
    start_time: time
    start_seconds: int
    end_seconds: int
    label: str
    evidence: tuple[Evidence, ...]
    zone: str | None
    why_matched: str
    key_frames: tuple[KeyFrame, ...]
    thumbnail_url: str | None = None

    def __post_init__(self) -> None:
        _check_id("clip id", self.id)
        _check_id("recording id", self.recording_id)
        if not 0 <= self.start_seconds < self.end_seconds:
            raise ValueError("a clip needs 0 <= start_seconds < end_seconds")
        if not self.label.strip():
            raise ValueError("clip label must not be blank")

    @property
    def duration(self) -> timedelta:
        """How long the clip lasts."""
        return timedelta(seconds=self.end_seconds - self.start_seconds)


@dataclass(frozen=True, slots=True)
class Zone:
    """A named polygon drawn on one camera's view, in frame fractions (0 to 1)."""

    id: str
    camera: str
    name: str
    points: tuple[ZonePoint, ...]

    def __post_init__(self) -> None:
        _check_id("zone id", self.id)
        _check_id("camera id", self.camera)
        if not self.name.strip():
            raise ValueError("zone name must not be blank")
        if len(self.points) < 3:
            raise ValueError("a zone needs at least 3 points")
        for x, y in self.points:
            if not (math.isfinite(x) and math.isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError("zone points must be fractions between 0 and 1")


@dataclass(frozen=True, slots=True)
class SavedClip:
    """A clip the user kept, with their note and when they saved it (UTC)."""

    id: str
    clip: Clip
    note: str
    saved_at: datetime

    def __post_init__(self) -> None:
        _check_id("saved clip id", self.id)
        if self.saved_at.tzinfo is None:
            raise ValueError("saved_at must be timezone-aware")


class RecordingStore(Protocol):
    """Cameras and their recordings."""

    def list_cameras(self) -> list[Camera]:
        """Every camera, ordered by id."""
        ...

    def get_camera(self, camera_id: str) -> Camera | None:
        """The camera with this id, or None."""
        ...

    def summarise_days(self, camera_id: str, first_day: date, last_day: date) -> list[DaySummary]:
        """Recording counts per day from first_day to last_day inclusive, oldest first.

        Only days with at least one recording appear; the caller fills in empty days.
        """
        ...

    def list_recordings(self, camera_id: str, day: date) -> list[Recording]:
        """One camera's recordings on one day, ordered by start_time, then id."""
        ...

    def get_recording(self, recording_id: str) -> Recording | None:
        """The recording with this id, or None."""
        ...

    def add_recording(self, recording: Recording) -> None:
        """Store a new recording.

        Raises DuplicateError if the id is taken, MissingReferenceError if the camera
        does not exist.
        """
        ...


class ClipStore(Protocol):
    """Clips found in recordings, with their evidence."""

    def list_clips(self, camera_id: str, day: date) -> list[Clip]:
        """Every clip in one camera's recordings on one day, ordered by start_time, then id."""
        ...

    def get_clip(self, clip_id: str) -> Clip | None:
        """The clip with this id, or None."""
        ...

    def add_clip(self, clip: Clip) -> None:
        """Store a new clip, keeping the order of its evidence and key frames.

        Raises DuplicateError if the id is taken, MissingReferenceError if the recording
        does not exist.
        """
        ...


class ZoneStore(Protocol):
    """Named zones drawn on camera views.

    A zone name is unique per camera, compared ignoring case (str.casefold): "Gate" and
    "gate" clash. The stored name keeps the case it was given.
    """

    def list_zones(self, camera_id: str | None = None) -> list[Zone]:
        """All zones, or only one camera's, ordered by name, then id."""
        ...

    def get_zone(self, zone_id: str) -> Zone | None:
        """The zone with this id, or None."""
        ...

    def add_zone(self, zone: Zone) -> None:
        """Store a new zone.

        Raises DuplicateError if the id is taken or the camera already has a zone with
        this name (ignoring case), MissingReferenceError if the camera does not exist.
        """
        ...

    def replace_zone(self, zone: Zone) -> bool:
        """Replace the name and points of the zone with zone.id; its camera never changes.

        Returns False if there is no such zone. Raises DuplicateError if another zone on
        the same camera already has the new name (ignoring case); renaming a zone to a
        different case of its own name is allowed.
        """
        ...

    def delete_zone(self, zone_id: str) -> bool:
        """Delete the zone; returns False if there was no such zone."""
        ...


class SavedClipStore(Protocol):
    """Clips the user saved, each with a note. A clip can be saved at most once."""

    def list_saved_clips(self, day: date | None = None) -> list[SavedClip]:
        """Saved clips, newest saved_at first, then id; only clips from `day` if given."""
        ...

    def get_saved_clip(self, saved_id: str) -> SavedClip | None:
        """The saved clip with this id, or None."""
        ...

    def add_saved_clip(
        self, saved_id: str, clip_id: str, note: str, saved_at: datetime
    ) -> SavedClip:
        """Save a clip with a note and return the saved clip.

        Raises MissingReferenceError if the clip does not exist, DuplicateError if the
        id is taken or the clip is already saved.
        """
        ...

    def update_note(self, saved_id: str, note: str) -> SavedClip | None:
        """Change the note; returns the saved clip after the change, or None if unknown."""
        ...

    def delete_saved_clip(self, saved_id: str) -> bool:
        """Remove a saved clip (the clip itself stays); returns False if it was not saved."""
        ...
