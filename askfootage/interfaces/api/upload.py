"""Read a recording upload: a multipart/form-data body with one MP4 file, day and camera.

Upload limit: MAX_UPLOAD_BYTES, 200 MiB (209,715,200 bytes) of video. It is enforced twice:
a declared Content-Length over the limit (plus FORM_OVERHEAD_BYTES for the boundaries and
the small day/camera fields) is refused with 413 before any of the body is read, and the
bytes are counted while they stream in, so a body without Content-Length, or one that
lies about it, is cut off as soon as it passes the limit.

In v1 (demo mode) the video is checked and then discarded: the parser streams it chunk by
chunk, keeps only its first 8 bytes for the MP4 check, and never writes it anywhere: no
temporary file, no spooling, no disk. Its filename is read only to check the .mp4
extension; it is never used in a path and never echoed back.

An MP4 must pass three checks, or the answer is 415: the filename ends in .mp4, the part's
Content-Type is video/mp4, and bytes 4 to 8 of the file are the "ftyp" box type.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, ValidationError
from python_multipart import MultipartParser
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import parse_options_header
from starlette.requests import ClientDisconnect, Request

from askfootage.interfaces.api.errors import ApiError, describe_validation_problems
from askfootage.interfaces.api.schemas import Day, Id

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
"""Largest video accepted: 200 MiB. Over it, the answer is 413 file_too_large."""
FORM_OVERHEAD_BYTES = 64 * 1024
"""Room in the body, beyond the video, for multipart boundaries, part headers and fields."""
MAX_FIELD_BYTES = 1024
"""Largest text field (day, camera) accepted."""
MAX_PARTS = 8
"""Most parts a form may have: the file, day, camera and a few ignored extras."""

_MP4_BOX_TYPE = b"ftyp"
_MP4_CONTENT_TYPE = b"video/mp4"
_FIELD_NAMES = ("day", "camera")


def _too_large(limit: int) -> ApiError:
    mib = limit / (1024 * 1024)
    size = f"{mib:g} MiB" if mib >= 1 else f"{limit} bytes"
    return ApiError(413, "file_too_large", f"The video is larger than the {size} limit.")


def _not_mp4() -> ApiError:
    return ApiError(415, "unsupported_media_type", "The upload must be an MP4 video (.mp4).")


def _invalid(message: str) -> ApiError:
    return ApiError(422, "validation_error", message)


class UploadFields(BaseModel):
    """The text fields of an upload, validated like any other input. Both are required."""

    model_config = ConfigDict(extra="ignore")

    day: Day
    camera: Id


@dataclass
class _Part:
    name: str | None = None
    filename: bytes | None = None
    content_type: bytes = b""
    disposition: bytes = b""
    is_file: bool = False
    size: int = 0
    head: bytearray = field(default_factory=bytearray)
    text: bytearray = field(default_factory=bytearray)


class _UploadReader:
    """Callbacks for python-multipart's streaming parser: check, count and discard."""

    def __init__(self, max_file_bytes: int) -> None:
        self.max_file_bytes = max_file_bytes
        self.fields: dict[str, str] = {}
        self.file_received = False
        self.finished = False
        self._parts = 0
        self._part = _Part()
        self._header_name = bytearray()
        self._header_value = bytearray()

    def callbacks(self) -> dict[str, object]:
        """The callback table MultipartParser expects."""
        return {
            "on_part_begin": self.on_part_begin,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_part_data": self.on_part_data,
            "on_part_end": self.on_part_end,
            "on_end": self.on_end,
        }

    def on_part_begin(self) -> None:
        """A new part starts."""
        self._parts += 1
        if self._parts > MAX_PARTS:
            raise _invalid("body: has too many form fields")
        self._part = _Part()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        """More of a part header's name."""
        self._header_name += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        """More of a part header's value."""
        self._header_value += data[start:end]

    def on_header_end(self) -> None:
        """A part header is complete; keep the two this reader needs."""
        name = bytes(self._header_name).strip().lower()
        if name == b"content-disposition":
            self._part.disposition = bytes(self._header_value)
        elif name == b"content-type":
            self._part.content_type = bytes(self._header_value)
        self._header_name.clear()
        self._header_value.clear()

    def on_headers_finished(self) -> None:
        """The part's headers are in: decide what the part is, and refuse non-MP4 early."""
        part = self._part
        _, options = parse_options_header(part.disposition)
        raw_name = options.get(b"name")
        if raw_name is None:
            raise _invalid("body: a form field has no name")
        part.name = raw_name.decode("utf-8", errors="replace")
        part.filename = options.get(b"filename")
        part.is_file = part.filename is not None
        if part.name != "file":
            if part.is_file:
                raise _invalid("body: send the video in the field named file")
            return
        if not part.is_file:
            raise _invalid("file: must be an uploaded file")
        if self.file_received:
            raise _invalid("file: send exactly one file")
        self.file_received = True
        filename = (part.filename or b"").decode("utf-8", errors="replace").strip().lower()
        content_type, _ = parse_options_header(part.content_type)
        if not filename.endswith(".mp4") or content_type.lower() != _MP4_CONTENT_TYPE:
            raise _not_mp4()

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        """Part data: count and discard file bytes; collect small text fields."""
        part = self._part
        if part.is_file:
            part.size += end - start
            if part.size > self.max_file_bytes:
                raise _too_large(self.max_file_bytes)
            if len(part.head) < 8:
                part.head += data[start : min(end, start + 8 - len(part.head))]
                if len(part.head) == 8:
                    self._check_mp4_head(part)
            return
        if len(part.text) + (end - start) > MAX_FIELD_BYTES:
            if part.name in _FIELD_NAMES:
                raise _invalid(f"{part.name}: is too long")
            raise _invalid("body: a form field is too long")
        part.text += data[start:end]

    def on_part_end(self) -> None:
        """A part is complete."""
        part = self._part
        if part.is_file:
            if len(part.head) < 8:
                raise _not_mp4()
            return
        if part.name not in _FIELD_NAMES:
            return
        if part.name in self.fields:
            raise _invalid(f"{part.name}: send it once")
        try:
            self.fields[part.name] = part.text.decode("utf-8")
        except UnicodeDecodeError:
            raise _invalid(f"{part.name}: must be UTF-8 text") from None

    def on_end(self) -> None:
        """The closing boundary was read."""
        self.finished = True

    @staticmethod
    def _check_mp4_head(part: _Part) -> None:
        if bytes(part.head[4:8]) != _MP4_BOX_TYPE:
            raise _not_mp4()


@dataclass(frozen=True, slots=True)
class CheckedUpload:
    """What is left of an upload once the video has passed its checks and been dropped."""

    fields: UploadFields


async def read_upload(request: Request, max_file_bytes: int = MAX_UPLOAD_BYTES) -> CheckedUpload:
    """Check an upload while it streams in, and return its validated text fields.

    Raises ApiError: 413 file_too_large, 415 unsupported_media_type (also for a body that
    is not multipart/form-data) or 422 validation_error.
    """
    content_type, options = parse_options_header(request.headers.get("content-type"))
    boundary = options.get(b"boundary")
    if content_type.lower() != b"multipart/form-data" or not boundary:
        raise ApiError(
            415,
            "unsupported_media_type",
            "Send the video as multipart/form-data with the MP4 in the field named file.",
        )

    max_body_bytes = max_file_bytes + FORM_OVERHEAD_BYTES
    declared_length = request.headers.get("content-length", "")
    if declared_length.isdigit() and int(declared_length) > max_body_bytes:
        raise _too_large(max_file_bytes)

    reader = _UploadReader(max_file_bytes)
    try:
        parser = MultipartParser(boundary, reader.callbacks())  # type: ignore[arg-type]
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > max_body_bytes:
                raise _too_large(max_file_bytes)
            parser.write(chunk)
        parser.finalize()
    except FormParserError:
        raise _invalid("body: is not valid multipart/form-data") from None
    except ClientDisconnect:
        raise _invalid("file: the upload did not finish") from None

    if not reader.finished:
        raise _invalid("body: the form ended early")
    if not reader.file_received:
        raise _invalid("file: is required")
    try:
        fields = UploadFields.model_validate(reader.fields)
    except ValidationError as error:
        problems = error.errors(include_input=False, include_url=False)
        raise _invalid(describe_validation_problems(problems)) from None
    return CheckedUpload(fields=fields)
