"""Request and response models of the HTTP API, one per schema in contract/openapi.yaml.

Each class is named after its contract schema, so the app's OpenAPI document uses the
same component names (tests/api/test_api_contract.py fails on any drift). JSON fields
are camelCase; Python attributes are snake_case. Request models reject unknown fields,
so a misspelt field is a 422 rather than silently ignored.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)
from pydantic.alias_generators import to_camel

from askfootage.application import cameras
from askfootage.application.cameras import CameraDraft, CameraOverview
from askfootage.application.clips import SavedClipWithCamera
from askfootage.application.errors import InvalidInputError
from askfootage.application.recordings import ServiceStatus
from askfootage.application.saved_clips import MAX_NOTE_LENGTH
from askfootage.application.search import MAX_QUESTION_LENGTH, SearchResult
from askfootage.application.zones import MAX_ZONE_NAME_LENGTH, MAX_ZONE_POINTS, MIN_ZONE_POINTS
from askfootage.ports import library_store as ports

ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
"""Every id, in paths and bodies: 1 to 64 letters, digits, '-' or '_'."""
CAMERA_ID_PATTERN = r"^CAM-[0-9]{3,}$"
"""A camera id as the server gives it out: CAM-001, CAM-002, ... CAM-1000."""
HOST_PATTERN = cameras.HOST_PATTERN
"""CameraCreate.ip: an IPv4 address or a host name (see askfootage.application.cameras)."""
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


def _by_rule[T](check: Callable[[T], T]) -> Callable[[T], T]:
    """A pydantic validator made from an application rule.

    The rule's InvalidInputError becomes a ValueError holding only the rule's own words,
    never the input, so the 422 message cannot echo what was sent.
    """

    def validate(value: T) -> T:
        try:
            return check(value)
        except InvalidInputError as error:
            raise ValueError(error.problem) from None

    return validate


def _true_only(value: object) -> object:
    """Accept only the JSON value true: not 1 and not "true" (pydantic alone takes 1)."""
    if value is not True:
        raise ValueError("must be true")
    return value


def _blank_to_none(value: str | None) -> str | None:
    """Trim optional text; blank after trimming becomes None."""
    if value is None:
        return None
    return value.strip() or None


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


# --- Status ---------------------------------------------------------------------------------


class Status(ResponseModel):
    """Whether the app serves demo data."""

    demo_mode: bool = Field(description="True when the app serves the seeded demo data")

    @classmethod
    def from_status(cls, status: ServiceStatus) -> Status:
        """The response model for the service status."""
        return cls(demo_mode=status.demo_mode)


# --- Cameras --------------------------------------------------------------------------------

_CAMERA_STATUS_DESCRIPTION = (
    "online: streaming; standby: reachable but not recording; offline: not reachable"
)
_OPTIONAL_TEXT_DESCRIPTION = "Optional; blank after trimming means null"

OptionalCameraText = Annotated[
    str | None,
    Field(max_length=cameras.MAX_CAMERA_TEXT_LENGTH),
    AfterValidator(_blank_to_none),
]
"""A location or department: optional, at most 80 characters; blank means null."""


class Camera(ResponseModel):
    """A camera in the registry, with what it holds. It never carries a password."""

    id: str = Field(
        pattern=CAMERA_ID_PATTERN,
        description=(
            "Given by the server in order: CAM-001, CAM-002, ... (CAM-1000 after CAM-999); "
            "never reused, even after a delete"
        ),
    )
    name: str = Field(min_length=1, max_length=cameras.MAX_CAMERA_NAME_LENGTH)
    location: str | None = Field(description="Where the camera is, or null")
    department: str | None = Field(description="Who looks after it, or null")
    ip: str = Field(description="IPv4 address or host name of the camera")
    status: ports.CameraStatus = Field(description=_CAMERA_STATUS_DESCRIPTION)
    rtsp_url_masked: str = Field(
        description=(
            "rtsp://<username>:****@<ip>:554/cam/realmonitor?channel=1&subtype=1, where "
            "<username> is the stream username percent-encoded (every character except "
            "A-Z a-z 0-9 - . _ ~ becomes %XX of its UTF-8 bytes, upper-case hex) and the "
            "password is always the four characters ****. The real password is never part "
            "of any response."
        )
    )
    zone_count: int = Field(ge=0)
    recording_count: int = Field(ge=0)
    saved_clip_count: int = Field(ge=0, description="Saved clips from this camera's recordings")
    created_at: datetime = Field(description="UTC, ending in Z")

    @classmethod
    def from_overview(cls, overview: CameraOverview) -> Camera:
        """The response model for a camera and its counts; createdAt is UTC to the second."""
        camera = overview.camera
        return cls(
            id=camera.id,
            name=camera.name,
            location=camera.location,
            department=camera.department,
            ip=camera.ip,
            status=camera.status,
            rtsp_url_masked=overview.rtsp_url_masked,
            zone_count=overview.counts.zones,
            recording_count=overview.counts.recordings,
            saved_clip_count=overview.counts.saved_clips,
            created_at=camera.created_at.astimezone(UTC).replace(microsecond=0),
        )


class CameraCreate(RequestModel):
    """A new camera. The password is checked for length and then dropped.

    password is left out of repr(), so printing or logging the model never shows it.
    """

    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=cameras.MAX_CAMERA_NAME_LENGTH,
            description=(
                "Not blank after trimming (stored trimmed); unique ignoring case "
                "(409 camera_name_taken)"
            ),
        ),
        AfterValidator(_by_rule(cameras.check_camera_name)),
    ]
    ip: Annotated[
        str,
        Field(
            min_length=1,
            max_length=cameras.MAX_HOST_LENGTH,
            pattern=HOST_PATTERN,
            description=(
                "An IPv4 address (four numbers 0-255 separated by dots) or a host name "
                "(labels of letters, digits and inner hyphens separated by dots). No spaces, "
                "scheme, port, user or path. A value made only of digits and dots must be a "
                "valid IPv4 address."
            ),
        ),
        AfterValidator(_by_rule(cameras.check_camera_ip)),
    ]
    username: str = Field(
        min_length=1,
        max_length=cameras.MAX_USERNAME_LENGTH,
        description="The stream username; shown inside rtspUrlMasked",
    )
    password: str = Field(
        min_length=1,
        max_length=cameras.MAX_PASSWORD_LENGTH,
        repr=False,
        json_schema_extra={"writeOnly": True},
        description=(
            "The stream password. Checked for length, then dropped: never stored, "
            "returned or logged"
        ),
    )
    location: OptionalCameraText = Field(default=None, description=_OPTIONAL_TEXT_DESCRIPTION)
    department: OptionalCameraText = Field(default=None, description=_OPTIONAL_TEXT_DESCRIPTION)
    acknowledge_cost: Annotated[Literal[True], BeforeValidator(_true_only)] = Field(
        description=(
            "Must be true: the user accepts that searching footage uses their Meta credits"
        )
    )

    def to_draft(self) -> CameraDraft:
        """The use case's input. The password goes along only to be checked and dropped."""
        return CameraDraft(
            name=self.name,
            ip=self.ip,
            username=self.username,
            password=self.password,
            location=self.location,
            department=self.department,
            acknowledge_cost=self.acknowledge_cost,
        )


class CameraUpdate(RequestModel):
    """A camera's new status; nothing else about a camera can change."""

    status: ports.CameraStatus


# --- Days and recordings ----------------------------------------------------------------------


class DaySummary(ResponseModel):
    """How many recordings a day has, and how many of them can be searched."""

    day: date
    recordings: int = Field(ge=0, description="Recordings made on this day")
    ready: int = Field(ge=0, description="Of those, how many can be searched")

    @classmethod
    def from_port(cls, summary: ports.DaySummary) -> DaySummary:
        """The response model for a stored day summary."""
        return cls(day=summary.day, recordings=summary.recordings, ready=summary.ready)


class Recording(ResponseModel):
    """One continuous video from one camera."""

    id: str = Field(pattern=ID_PATTERN)
    camera: str = Field(pattern=ID_PATTERN, description="The id of the camera that made it")
    day: date
    start_time: str = Field(pattern=TIME_PATTERN)
    length_seconds: int = Field(ge=0)
    status: ports.RecordingStatus

    @classmethod
    def from_port(cls, recording: ports.Recording) -> Recording:
        """The response model for a stored recording."""
        return cls(
            id=recording.id,
            camera=recording.camera,
            day=recording.day,
            start_time=recording.start_time.strftime("%H:%M:%S"),
            length_seconds=recording.length_seconds,
            status=recording.status,
        )


class RecordingAccepted(ResponseModel):
    """An upload was accepted and now waits to be processed."""

    id: str = Field(pattern=ID_PATTERN)
    status: Literal["waiting"]


class IndexAccepted(ResponseModel):
    """Indexing was accepted; the recording is now being prepared."""

    id: str = Field(pattern=ID_PATTERN)
    status: Literal["preparing"]


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
    camera: str = Field(
        pattern=ID_PATTERN, description="The id of the camera that made the recording"
    )
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
    def from_port(cls, clip: ports.Clip, camera: str) -> Clip:
        """The response model for a stored clip and its recording's camera."""
        return cls(
            id=clip.id,
            recording_id=clip.recording_id,
            camera=camera,
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
    """A question about one day of footage, from one camera or (camera null) all of them."""

    question: str = Field(
        min_length=1, max_length=MAX_QUESTION_LENGTH, description="Not blank after trimming"
    )
    day: Day
    camera: Id | None = Field(
        default=None, description="A camera id; null or left out searches every camera"
    )

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
            clips=[Clip.from_port(found.clip, found.camera) for found in result.clips],
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
    def from_found(cls, found: SavedClipWithCamera) -> SavedClip:
        """The response model for a saved clip and its camera; savedAt is UTC to the second."""
        saved = found.saved
        saved_at = saved.saved_at.astimezone(UTC).replace(microsecond=0)
        clip = Clip.from_port(saved.clip, found.camera)
        return cls(id=saved.id, clip=clip, note=saved.note, saved_at=saved_at)


class SavedClipCreate(RequestModel):
    """The clip to save, and an optional note."""

    clip_id: Id
    note: Note = ""


class SavedClipUpdate(RequestModel):
    """A saved clip's new note."""

    note: Note
