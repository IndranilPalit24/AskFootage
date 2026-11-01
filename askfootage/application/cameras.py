"""Use cases for the camera registry: list, look up, add, change status and delete.

The store gives each new camera the next id (CAM-001, CAM-002, ...). A camera's stream
password is checked when the camera is added and then dropped: it is never put in
NewCamera, never handed to the store, never returned and never placed in a log or error
message. What is kept is the username and address, and the stream URL is shown with the
password masked as ****.

Every InvalidInputError here names the field and the rule; none repeats the input.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from askfootage.application.errors import (
    CameraNameTakenError,
    ConflictError,
    InvalidInputError,
    NotFoundError,
)
from askfootage.application.library import CAMERA_NOT_FOUND, Library
from askfootage.ports.library_store import (
    CAMERA_NAME_MAX,
    CAMERA_STATUSES,
    CAMERA_TEXT_MAX,
    CAMERA_USERNAME_MAX,
    Camera,
    CameraCounts,
    CameraStatus,
    DuplicateError,
    NewCamera,
    camera_number,
)

MAX_CAMERA_NAME_LENGTH = CAMERA_NAME_MAX
"""Longest camera name accepted, in characters, before trimming (80)."""
MAX_CAMERA_TEXT_LENGTH = CAMERA_TEXT_MAX
"""Longest location or department accepted, in characters, before trimming (80)."""
MAX_USERNAME_LENGTH = CAMERA_USERNAME_MAX
"""Longest stream username accepted (64)."""
MAX_PASSWORD_LENGTH = 128
"""Longest stream password accepted. The password is only checked, never kept."""
MAX_HOST_LENGTH = 253
"""Longest IPv4 address or host name accepted."""

HOST_PATTERN = (
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)
"""An IPv4 address or a host name: dot-separated labels of letters, digits and inner hyphens.

The same text as CameraCreate.ip's pattern in contract/openapi.yaml.
"""
HOST_PROBLEM = "must be an IPv4 address or a host name, with no spaces, scheme, port, user or path"
IPV4_PROBLEM = "must be a valid IPv4 address: four numbers from 0 to 255 separated by dots"

RTSP_PORT = 554
RTSP_PATH = "/cam/realmonitor?channel=1&subtype=1"
MASKED_PASSWORD = "****"
"""What stands in for the password in every stream URL the API shows."""

INITIAL_STATUS: CameraStatus = "online"
"""The status a camera has when it is added."""

_HOST = re.compile(HOST_PATTERN)
_DIGITS_AND_DOTS = re.compile(r"[0-9.]+")
_UNRESERVED = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_NO_COUNTS = CameraCounts(recordings=0, zones=0, saved_clips=0)
_NAME_TAKEN = "Another camera already has that name."


class CameraHasRecordingsError(ConflictError):
    """The camera still has recordings and the caller did not ask to delete them too.

    The message says how many recordings and saved clips it has, in plain English.
    """


# --- The masked stream URL ---------------------------------------------------------------------


def percent_encode(text: str) -> str:
    """Percent-encode text for the user part of a URL (RFC 3986).

    Every character except A-Z a-z 0-9 - . _ ~ becomes %XX for each of its UTF-8 bytes,
    in upper-case hex. The UI implements the same rule; these examples must hold in both:

        "yard.viewer" -> "yard.viewer"
        "a@b:c"       -> "a%40b%3Ac"
        "a b/c"       -> "a%20b%2Fc"
        "50%"         -> "50%25"
        "José"        -> "Jos%C3%A9"
        "~u_1-2"      -> "~u_1-2"
    """
    return "".join(
        chr(byte) if byte in _UNRESERVED else f"%{byte:02X}" for byte in text.encode("utf-8")
    )


def masked_rtsp_url(username: str, ip: str) -> str:
    """The camera's stream URL with the password shown as ****.

    rtsp://<username>:****@<ip>:554/cam/realmonitor?channel=1&subtype=1, with the
    username percent-encoded by percent_encode(). For example, username "a@b:c" and ip
    "10.0.0.5" give "rtsp://a%40b%3Ac:****@10.0.0.5:554/cam/realmonitor?channel=1&subtype=1".
    The real password is never an input, so it can never be part of the result.
    """
    return f"rtsp://{percent_encode(username)}:{MASKED_PASSWORD}@{ip}:{RTSP_PORT}{RTSP_PATH}"


# --- Views and drafts ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CameraOverview:
    """A camera with what it holds: its recordings, zones and saved clips."""

    camera: Camera
    counts: CameraCounts

    @property
    def rtsp_url_masked(self) -> str:
        """The stream URL with the password masked as ****."""
        return masked_rtsp_url(self.camera.username, self.camera.ip)


@dataclass(frozen=True, slots=True)
class CameraDraft:
    """What a client sends to add a camera, before it is checked.

    password is checked for length and then dropped by add_camera(). It is left out of
    repr() so it cannot end up in a log line or an error message by accident.
    """

    name: str
    ip: str
    username: str
    password: str = field(repr=False)
    location: str | None = None
    department: str | None = None
    acknowledge_cost: bool = False


# --- Rules ---------------------------------------------------------------------------------------


def check_camera_name(name: str) -> str:
    """The name trimmed; raises InvalidInputError if it is too long or blank."""
    if len(name) > MAX_CAMERA_NAME_LENGTH:
        raise InvalidInputError("name", f"must be at most {MAX_CAMERA_NAME_LENGTH} characters")
    trimmed = name.strip()
    if not trimmed:
        raise InvalidInputError("name", "must not be blank")
    return trimmed


def check_camera_ip(ip: str) -> str:
    """The address unchanged; raises InvalidInputError unless it is IPv4 or a host name.

    No spaces, scheme, port, user or path are allowed, and a value made only of digits
    and dots must be a valid IPv4 address (so 256.1.1.1 and 1.2.3 are refused).
    """
    if not ip:
        raise InvalidInputError("ip", "must not be empty")
    if len(ip) > MAX_HOST_LENGTH:
        raise InvalidInputError("ip", f"must be at most {MAX_HOST_LENGTH} characters")
    if _HOST.fullmatch(ip) is None:
        raise InvalidInputError("ip", HOST_PROBLEM)
    if _DIGITS_AND_DOTS.fullmatch(ip) is not None:
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            raise InvalidInputError("ip", IPV4_PROBLEM) from None
    return ip


def check_username(username: str) -> str:
    """The username unchanged; raises InvalidInputError unless it is 1 to 64 characters."""
    if not 1 <= len(username) <= MAX_USERNAME_LENGTH:
        raise InvalidInputError("username", f"must be 1 to {MAX_USERNAME_LENGTH} characters")
    return username


def check_password(password: str) -> None:
    """Raise InvalidInputError unless the password is 1 to 128 characters.

    Returns nothing on purpose, so the password cannot be passed on from here.
    """
    if not 1 <= len(password) <= MAX_PASSWORD_LENGTH:
        raise InvalidInputError("password", f"must be 1 to {MAX_PASSWORD_LENGTH} characters")


def check_camera_text(field_name: str, value: str | None) -> str | None:
    """An optional location or department, trimmed; blank becomes None.

    Raises InvalidInputError if it is longer than 80 characters.
    """
    if value is None:
        return None
    if len(value) > MAX_CAMERA_TEXT_LENGTH:
        raise InvalidInputError(field_name, f"must be at most {MAX_CAMERA_TEXT_LENGTH} characters")
    return value.strip() or None


def check_camera_status(status: str) -> CameraStatus:
    """The status; raises InvalidInputError unless it is online, standby or offline."""
    for known in CAMERA_STATUSES:
        if status == known:
            return known
    *first, last = CAMERA_STATUSES
    raise InvalidInputError("status", f"must be {', '.join(first)} or {last}")


def camera_sort_key(camera_id: str) -> tuple[int, int, str]:
    """Sort camera ids by the number in them: CAM-999 comes before CAM-1000.

    Ids that are not CAM-<number> (none should exist) sort after all others, by text.
    """
    try:
        return (0, camera_number(camera_id), "")
    except ValueError:
        return (1, 0, camera_id)


# --- Use cases -----------------------------------------------------------------------------------


def list_cameras(library: Library) -> list[CameraOverview]:
    """Every camera with its counts, in id order (which is creation order)."""
    counts = library.cameras.camera_counts()
    cameras = sorted(library.cameras.list_cameras(), key=lambda camera: camera_sort_key(camera.id))
    return [CameraOverview(camera, counts.get(camera.id, _NO_COUNTS)) for camera in cameras]


def get_camera(library: Library, camera_id: str) -> CameraOverview:
    """One camera with its counts; raises NotFoundError when there is no such camera."""
    camera = library.cameras.get_camera(camera_id)
    if camera is None:
        raise NotFoundError(CAMERA_NOT_FOUND)
    return CameraOverview(camera, library.cameras.camera_counts().get(camera.id, _NO_COUNTS))


def add_camera(library: Library, draft: CameraDraft, now: datetime) -> CameraOverview:
    """Check a new camera, drop its password, and store it under the next id.

    The camera starts online, created `now` (UTC, to the whole second). Raises
    InvalidInputError for a broken rule (including acknowledge_cost not being True) and
    CameraNameTakenError when another camera has the same name, ignoring case.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    name = check_camera_name(draft.name)
    ip = check_camera_ip(draft.ip)
    username = check_username(draft.username)
    check_password(draft.password)
    location = check_camera_text("location", draft.location)
    department = check_camera_text("department", draft.department)
    if draft.acknowledge_cost is not True:
        raise InvalidInputError("acknowledgeCost", "must be true")

    # The password stops here: NewCamera has no field for it.
    new_camera = NewCamera(
        name=name,
        ip=ip,
        username=username,
        status=INITIAL_STATUS,
        location=location,
        department=department,
        created_at=now.astimezone(UTC).replace(microsecond=0),
    )
    if _name_taken(library, name):
        raise CameraNameTakenError(_NAME_TAKEN)
    try:
        camera = library.cameras.add_camera(new_camera)
    except DuplicateError:
        if _name_taken(library, name):
            raise CameraNameTakenError(_NAME_TAKEN) from None
        raise
    return CameraOverview(camera, _NO_COUNTS)


def set_camera_status(library: Library, camera_id: str, status: str) -> CameraOverview:
    """Change a camera's status and return it with its counts.

    Raises InvalidInputError for an unknown status and NotFoundError for an unknown camera.
    """
    checked = check_camera_status(status)
    camera = library.cameras.set_camera_status(camera_id, checked)
    if camera is None:
        raise NotFoundError(CAMERA_NOT_FOUND)
    return CameraOverview(camera, library.cameras.camera_counts().get(camera.id, _NO_COUNTS))


def delete_camera(library: Library, camera_id: str, *, delete_recordings: bool = False) -> None:
    """Delete a camera; its recordings are only deleted along with it when asked.

    A camera with no recordings is deleted at once. A camera with recordings is left
    untouched and CameraHasRecordingsError is raised, unless delete_recordings is True, in
    which case it goes with its recordings, clips, saved clips and zones. Raises
    NotFoundError when there is no such camera (so a second delete is 404).
    """
    if not delete_recordings:
        counts = library.cameras.camera_counts().get(camera_id)
        if counts is not None and counts.recordings > 0:
            raise CameraHasRecordingsError(_has_recordings_message(counts))
    if not library.cameras.delete_camera(camera_id):
        raise NotFoundError(CAMERA_NOT_FOUND)


def _has_recordings_message(counts: CameraCounts) -> str:
    recordings = _plural(counts.recordings, "recording")
    saved = _plural(counts.saved_clips, "saved clip")
    return (
        f"This camera has {recordings} and {saved}. Deleting it would delete them too; "
        "confirm to delete the camera together with its recordings."
    )


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _name_taken(library: Library, name: str) -> bool:
    wanted = name.casefold()
    return any(camera.name.casefold() == wanted for camera in library.cameras.list_cameras())
