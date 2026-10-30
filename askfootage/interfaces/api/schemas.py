"""Request and response models of the HTTP API, one per schema in contract/openapi.yaml.

Each class is named after its contract schema, so the app's OpenAPI document uses the
same component names (tests/api/test_api_contract.py fails on any drift). JSON fields
are camelCase; Python attributes are snake_case. Request models reject unknown fields,
so a misspelt field is a 422 rather than silently ignored.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)
from pydantic.alias_generators import to_camel

from askfootage.application.recordings import ServiceStatus
from askfootage.application.saved_clips import MAX_NOTE_LENGTH
from askfootage.application.search import MAX_QUESTION_LENGTH, SearchResult
from askfootage.application.zones import MAX_ZONE_NAME_LENGTH, MAX_ZONE_POINTS, MIN_ZONE_POINTS
from askfootage.ports import library_store as ports

ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
"""Every id, in paths and bodies: 1 to 64 letters, digits, '-' or '_'."""
TIME_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]$"
_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _iso_day_only(value: object) -> object:
    """Accept only YYYY-MM-DD text; pydantic alone would also take numbers as timestamps."""
    if isinstance(value, str) and _ISO_DAY.fullmatch(value):
        return value
    raise ValueError("must be a date written YYYY-MM-DD")


Day = Annotated[date, BeforeValidator(_iso_day_only)]
"""A calendar day sent by a client, written YYYY-MM-DD."""
Id = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
"""An id sent by a client."""
Fraction = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
Point = tuple[Fraction, Fraction]
"""[x, y] as fractions of the frame's width and height, from the top-left corner."""
Points = Annotated[list[Point], Field(min_length=MIN_ZONE_POINTS, max_length=MAX_ZONE_POINTS)]
ZoneName = Annotated[str, Field(min_length=1, max_length=MAX_ZONE_NAME_LENGTH)]
Note = Annotated[str, Field(max_length=MAX_NOTE_LENGTH)]


def _not_blank(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("must not be blank")
    return trimmed


class RequestModel(BaseModel):
    """A JSON request body: camelCase names only, unknown fields rejected."""

    model_config = ConfigDict(alias_generator=to_camel, extra="forbid")


class ResponseModel(BaseModel):
    """A JSON response body: built in Python by attribute name, sent with camelCase names."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


# --- Errors ---------------------------------------------------------------------------------


class ErrorDetail(ResponseModel):
    """A machine-readable code and a plain-English message, safe to show to a person."""

    code: str
    message: str


class Error(ResponseModel):
    """The body of every error response."""

    error: ErrorDetail


# --- Status, days and recordings --------------------------------------------------------------


class Camera(ResponseModel):
    """A fixed camera."""

    id: str = Field(pattern=ID_PATTERN)
    name: str

    @classmethod
    def from_port(cls, camera: ports.Camera) -> Camera:
        """The response model for a stored camera."""
        return cls(id=camera.id, name=camera.name)


class Status(ResponseModel):
    """Whether the app serves demo data, and the camera it covers."""

    demo_mode: bool
    camera: Camera

    @classmethod
    def from_status(cls, status: ServiceStatus) -> Status:
        """The response model for the service status."""
        return cls(demo_mode=status.demo_mode, camera=Camera.from_port(status.camera))


class DaySummary(ResponseModel):
    """How many recordings a day has, and how many of them can be searched."""

    day: date
    recordings: int = Field(ge=0)
    ready: int = Field(ge=0)

    @classmethod
    def from_port(cls, summary: ports.DaySummary) -> DaySummary:
        """The response model for a stored day summary."""
        return cls(day=summary.day, recordings=summary.recordings, ready=summary.ready)


class Recording(ResponseModel):
    """One continuous video from one camera."""

    id: str = Field(pattern=ID_PATTERN)
    day: date
    start_time: str = Field(pattern=TIME_PATTERN)
    length_seconds: int = Field(ge=0)
    status: ports.RecordingStatus

    @classmethod
    def from_port(cls, recording: ports.Recording) -> Recording:
        """The response model for a stored recording."""
        return cls(
            id=recording.id,
            day=recording.day,
            start_time=recording.start_time.strftime("%H:%M:%S"),
            length_seconds=recording.length_seconds,
            status=recording.status,
        )


class RecordingAccepted(ResponseModel):
    """An upload was accepted and now waits to be processed."""

    id: str = Field(pattern=ID_PATTERN)
    status: Literal["waiting"]


# --- Clips and search ---------------------------------------------------------------------


class Evidence(ResponseModel):
    """One measured reason a clip matched, with its short chip text."""

    kind: ports.EvidenceKind
    text: str


class KeyFrame(ResponseModel):
    """A frame worth looking at, in seconds from the start of the recording."""

    at_seconds: int = Field(ge=0)
    image_url: str | None


class Clip(ResponseModel):
    """A stretch of one recording that answers a question, with the evidence for it."""

    id: str = Field(pattern=ID_PATTERN)
    recording_id: str = Field(pattern=ID_PATTERN)
    day: date
    start_time: str = Field(pattern=TIME_PATTERN)
    start_seconds: int = Field(ge=0)
    end_seconds: int = Field(ge=1)
    label: str
    evidence: list[Evidence]
    zone: str | None
    why_matched: str
    key_frames: list[KeyFrame]
    thumbnail_url: str | None

    @classmethod
    def from_port(cls, clip: ports.Clip) -> Clip:
        """The response model for a stored clip."""
        return cls(
            id=clip.id,
            recording_id=clip.recording_id,
            day=clip.day,
            start_time=clip.start_time.strftime("%H:%M:%S"),
            start_seconds=clip.start_seconds,
            end_seconds=clip.end_seconds,
            label=clip.label,
            evidence=[Evidence(kind=item.kind, text=item.text) for item in clip.evidence],
            zone=clip.zone,
            why_matched=clip.why_matched,
            key_frames=[
                KeyFrame(at_seconds=frame.at_seconds, image_url=frame.image_url)
                for frame in clip.key_frames
            ],
            thumbnail_url=clip.thumbnail_url,
        )


class SearchRequest(RequestModel):
    """A question about one day of one camera's footage."""

    question: str = Field(
        min_length=1, max_length=MAX_QUESTION_LENGTH, description="Not blank after trimming"
    )
    day: Day
    camera: Id

    _question_not_blank = field_validator("question")(_not_blank)


class SearchResponse(ResponseModel):
    """The matching clips, earliest first, and what the answer left out."""

    question: str
    day: date
    clips: list[Clip]
    note: str | None

    @classmethod
    def from_result(cls, result: SearchResult) -> SearchResponse:
        """The response model for a search result."""
        return cls(
            question=result.question,
            day=result.day,
            clips=[Clip.from_port(clip) for clip in result.clips],
            note=result.note,
        )


# --- Zones ----------------------------------------------------------------------------------


class Zone(ResponseModel):
    """A named polygon drawn on one camera's view."""

    id: str = Field(pattern=ID_PATTERN)
    camera: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=MAX_ZONE_NAME_LENGTH)
    points: Points

    @classmethod
    def from_port(cls, zone: ports.Zone) -> Zone:
        """The response model for a stored zone."""
        return cls(id=zone.id, camera=zone.camera, name=zone.name, points=list(zone.points))


class ZoneCreate(RequestModel):
    """A new zone: its camera, a name unique on that camera, and 3 to 50 points."""

    camera: Id
    name: ZoneName = Field(description="Not blank after trimming; unique per camera")
    points: Points

    _name_not_blank = field_validator("name")(_not_blank)


class ZoneUpdate(RequestModel):
    """A zone's new name and points; its camera never changes."""

    name: ZoneName
    points: Points

    _name_not_blank = field_validator("name")(_not_blank)


# --- Saved clips ------------------------------------------------------------------------------


class SavedClip(ResponseModel):
    """A clip the user kept, with their note and when they saved it (UTC, ending in Z)."""

    id: str = Field(pattern=ID_PATTERN)
    clip: Clip
    note: str = Field(max_length=MAX_NOTE_LENGTH)
    saved_at: datetime

    @classmethod
    def from_port(cls, saved: ports.SavedClip) -> SavedClip:
        """The response model for a stored saved clip; savedAt is UTC to the whole second."""
        saved_at = saved.saved_at.astimezone(UTC).replace(microsecond=0)
        return cls(id=saved.id, clip=Clip.from_port(saved.clip), note=saved.note, saved_at=saved_at)


class SavedClipCreate(RequestModel):
    """The clip to save, and an optional note."""

    clip_id: Id
    note: Note = ""


class SavedClipUpdate(RequestModel):
    """A saved clip's new note."""

    note: Note
