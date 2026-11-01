"""SAM 3.1 perception: ask the Meta API to find and follow every object matching a noun.

SamPerception implements ports/perception.py. For one prepared video it uploads the file
once (POST /files), then asks POST /responses (model sam-3.1, stream on) once per noun and
turns the reply into domain Tracks. Every call goes through a Transport, so a
ReplayTransport answers from saved recordings and nothing touches the network or a key.

The reply is a server-sent-events stream (verified against the real replies saved in
data/spike):

    event: response.created ... response.in_progress ... response.output_item.added
    event: response.content_part.added
    event: response.output_text.delta     (one per frame that has detections)
    event: response.output_text.done / response.content_part.done / response.output_item.done
    event: response.completed             (status "completed", usage.video_frames_processed)
    data: [DONE]

The text those deltas add up to has one line per frame with detections:

    <{frame}f>{id}<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..;c=..|><|mask;...|>[,{id}<|box...|><|mask...|>]

Frame numbers are 0-based indexes into the prepared 5 fps video (frame 0 is its first
frame; seconds = frame / 5). Boxes are pixels of that video, w and h its size, c the
confidence. Several objects on one frame share a line, separated by commas. An empty text
means nothing was found. Masks are never decoded or kept: parsing skips them, and
strip_masks() removes them from a reply before it is saved.

Errors are PerceptionErrors with fixed, short messages: they never carry mask data, a key
or a path.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from askfootage.adapters.meta.transport import (
    FileUpload,
    MetaApiError,
    MetaConnectionError,
    MetaError,
    MetaRequest,
    RecordingCorruptError,
    RecordingNotFoundError,
    Transport,
)
from askfootage.domain.models import BoundingBox
from askfootage.domain.timebase import DEFAULT_ANALYSIS_FPS, Timebase
from askfootage.domain.tracks import Track, TrackPoint
from askfootage.ports.perception import PerceptionError, PerceptionNotSentError
from askfootage.settings import MissingApiKeyError

SAM_MODEL = "sam-3.1"
UPLOAD_PURPOSE = "user_data"
DEFAULT_PROMPTS: Mapping[str, str] = {"cardboard box": "box"}
"""Vocabulary noun -> the words SAM was asked for. A noun not listed is sent as it is.

The saved replies were asked for "box"; the vocabulary's noun is "cardboard box", and the
tracks keep that label so a question about a cardboard box reaches them.
"""

_KNOWN_EVENTS = frozenset(
    {
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    }
)
_FAILURE_EVENTS = frozenset({"response.failed", "response.incomplete", "error"})
_EVENT_NAME = re.compile(r"[A-Za-z0-9_.]{1,60}")
_EXCERPT_CHARS = 24
_NUMBER = r"-?\d+(?:\.\d+)?"
_FRAME = re.compile(r"<(\d+)f>")
_OBJECT = re.compile(
    rf"(\d+)<\|box;x1=({_NUMBER});y1=({_NUMBER});x2=({_NUMBER});y2=({_NUMBER});"
    rf"w=(\d+);h=(\d+);c=({_NUMBER}(?:[eE][+-]?\d+)?)\|>"
)
_MASK_END = r"(?=\n|\Z|,\d+<\|box;)"
_MASK = re.compile(rf"<\|mask;.*?\|>{_MASK_END}", re.DOTALL)
# The same, inside the JSON text of an event, where a newline is written as the two
# characters backslash and n and the text ends at a closing quote.
_MASK_IN_JSON = re.compile(r'<\|mask;.*?\|>(?=\\n|"|,\d+<\|box;)', re.DOTALL)


class SamStreamError(PerceptionError):
    """The reply from SAM could not be read: unknown, failed or truncated. Safe to show."""


@dataclass(frozen=True, slots=True)
class SamDetection:
    """One object on one frame, as SAM reported it.

    frame is the 0-based index into the prepared video and time_s = frame / fps. box is in
    pixels of the prepared video (frame_width x frame_height); norm_box is the same box
    divided by that size and clamped to 0..1. object_id is SAM's id for the object within
    one noun's reply. There is no mask: masks are not read.
    """

    frame: int
    time_s: float
    object_id: int
    box: BoundingBox
    norm_box: BoundingBox
    confidence: float
    frame_width: int
    frame_height: int


# --- reading the stream --------------------------------------------------------------------


def _blocks(body: str) -> Iterator[tuple[str | None, str]]:
    """(event name, data text) for each block of the stream; the name is None for [DONE]."""
    if not isinstance(body, str) or not body.strip():
        raise SamStreamError("The SAM reply is empty.")
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name: str | None = None
        data: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data.append(line[len("data: ") :])
            else:
                raise SamStreamError("The SAM reply is not a server-sent-events stream.")
        if not data:
            raise SamStreamError("The SAM reply is not a server-sent-events stream.")
        yield name, "\n".join(data)


def _event_data(name: str | None, data: str) -> dict[str, Any] | None:
    """The decoded JSON of a known event; None for the [DONE] marker."""
    if name is None:
        if data.strip() == "[DONE]":
            return None
        raise SamStreamError("The SAM reply has data that belongs to no event.")
    if name in _FAILURE_EVENTS:
        raise SamStreamError(f"The SAM service reported a failure ({name}).")
    if name not in _KNOWN_EVENTS:
        shown = name if _EVENT_NAME.fullmatch(name) else "(unreadable name)"
        raise SamStreamError(f"The SAM reply has an unknown event type: {shown}.")
    try:
        decoded = json.loads(data)
    except ValueError:
        raise SamStreamError(f"The SAM reply is truncated: {name} is not complete JSON.") from None
    if not isinstance(decoded, dict) or decoded.get("type") != name:
        raise SamStreamError(f"The SAM reply is inconsistent: {name} carries a different type.")
    return decoded


def _final_text(completed: dict[str, Any]) -> str:
    response = completed.get("response")
    if not isinstance(response, dict):
        raise SamStreamError("The SAM reply has a response.completed without a response.")
    if response.get("status") != "completed" or response.get("error") is not None:
        raise SamStreamError("The SAM response did not finish: its status is not completed.")
    texts = [
        part.get("text")
        for item in response.get("output") or []
        if isinstance(item, dict)
        for part in item.get("content") or []
        if isinstance(part, dict) and part.get("type") == "output_text"
    ]
    if not all(isinstance(text, str) for text in texts):
        raise SamStreamError("The SAM reply has output text that is not text.")
    return "".join(texts)  # type: ignore[arg-type]


def _read_stream(body: str) -> str:
    """The reply's detection text, after checking the stream is whole and consistent."""
    deltas: list[str] = []
    done_texts: list[str] = []
    final: str | None = None
    finished = False
    for name, data in _blocks(body):
        if finished:
            raise SamStreamError("The SAM reply has events after its end marker.")
        decoded = _event_data(name, data)
        if decoded is None:
            finished = True
        elif final is not None:
            raise SamStreamError("The SAM reply has events after response.completed.")
        elif name == "response.output_text.delta":
            deltas.append(str(decoded.get("delta", "")))
        elif name == "response.output_text.done":
            done_texts.append(str(decoded.get("text", "")))
        elif name == "response.completed":
            final = _final_text(decoded)
    if final is None:
        raise SamStreamError("The SAM reply is truncated: it ended before response.completed.")
    streamed = "".join(deltas)
    if (deltas and streamed != final) or any(text != final for text in done_texts):
        raise SamStreamError("The SAM reply's streamed text does not match its final text.")
    return final


def _fail(text: str, position: int, expected: str) -> SamStreamError:
    line = text.count("\n", 0, position) + 1
    near = text[position : position + _EXCERPT_CHARS].replace("\n", " ")
    return SamStreamError(f"SAM detection text, line {line}: expected {expected} at {near!r}.")


def _parse_text(text: str, timebase: Timebase) -> list[SamDetection]:
    found: list[SamDetection] = []
    seen: set[tuple[int, int]] = set()
    size: tuple[int, int] | None = None
    position = 0
    while position < len(text):
        frame_match = _FRAME.match(text, position)
        if frame_match is None:
            raise _fail(text, position, "a frame marker like <3f>")
        frame = int(frame_match.group(1))
        position = frame_match.end()
        while True:
            start = position
            match = _OBJECT.match(text, position)
            if match is None:
                raise _fail(text, position, "an object id and a box")
            position = match.end()
            mask = _MASK.match(text, position)
            if mask is not None:
                position = mask.end()
            width, height = int(match.group(6)), int(match.group(7))
            if size is None:
                size = (width, height)
            elif size != (width, height):
                raise SamStreamError(
                    f"SAM detection text, line {text.count(chr(10), 0, start) + 1}: "
                    "the frame size changes inside one reply."
                )
            found.append(_detection(text, start, frame, match, size, timebase))
            key = (frame, found[-1].object_id)
            if key in seen:
                raise SamStreamError(f"SAM reported object {key[1]} twice on frame {frame}.")
            seen.add(key)
            if text.startswith(",", position):
                position += 1
                continue
            break
        if position < len(text):
            if text[position] != "\n":
                raise _fail(text, position, "the end of the line")
            position += 1
    return found


def _detection(
    text: str,
    start: int,
    frame: int,
    match: re.Match[str],
    size: tuple[int, int],
    timebase: Timebase,
) -> SamDetection:
    x1, y1, x2, y2, confidence = (float(match.group(i)) for i in (2, 3, 4, 5, 8))
    width, height = size
    if width <= 0 or height <= 0 or not math.isfinite(confidence):
        raise _fail(text, start, "a positive frame size and a finite confidence")
    try:
        box = BoundingBox(x1, y1, x2, y2)
        norm = BoundingBox(
            _unit(x1 / width), _unit(y1 / height), _unit(x2 / width), _unit(y2 / height)
        )
    except ValueError:
        raise _fail(text, start, "a box whose corners are in order") from None
    return SamDetection(
        frame=frame,
        time_s=timebase.frame_to_seconds(frame),
        object_id=int(match.group(1)),
        box=box,
        norm_box=norm,
        confidence=confidence,
        frame_width=width,
        frame_height=height,
    )


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))


def parse_sam_stream(body: str, *, fps: float = DEFAULT_ANALYSIS_FPS) -> list[SamDetection]:
    """Every detection in a SAM reply, in the order SAM gave them.

    An empty list means SAM found nothing. Raises SamStreamError for an empty or truncated
    stream, an unknown or failure event, an unfinished response, streamed text that
    disagrees with the final text, or a detection line that does not follow the format.
    """
    return _parse_text(_read_stream(body), Timebase(fps))


def tracks_from_detections(noun: str, detections: Sequence[SamDetection]) -> list[Track]:
    """One Track per SAM object id, labelled `noun`, ordered by id; boxes in pixels."""
    points: dict[int, list[TrackPoint]] = {}
    for detection in sorted(detections, key=lambda d: (d.object_id, d.frame)):
        points.setdefault(detection.object_id, []).append(
            TrackPoint(detection.frame, detection.box)
        )
    return [Track(object_id, noun, tuple(found)) for object_id, found in sorted(points.items())]


def strip_masks(body: str) -> str:
    """The reply with every mask removed, everything else byte for byte as it was.

    Masks are most of a reply (several MB for a person) and are never used, so a saved
    recording keeps only the boxes. The request fingerprint does not depend on the reply,
    so a stripped recording still replays. Idempotent. Raises SamStreamError when `body` is
    not a SAM stream, so a damaged reply is never saved as if it were whole.
    """
    for name, data in _blocks(body):  # refuses anything that is not a stream of events
        if name is None and data.strip() != "[DONE]":
            raise SamStreamError("The SAM reply has data that belongs to no event.")
    return _MASK_IN_JSON.sub("", body)


def redact_sam_reply(request: MetaRequest, body: str) -> str:
    """What a recording keeps of a reply: a /responses stream without masks, else the body.

    Pass it as RecordingTransport(..., redact=redact_sam_reply).
    """
    return strip_masks(body) if request.path == "/responses" else body


# --- requests ------------------------------------------------------------------------------


def sam_request(prompt: str, video_part: Mapping[str, str], *, stream: bool = True) -> MetaRequest:
    """The /responses request asking SAM to find `prompt` in the video given by `video_part`."""
    return MetaRequest(
        "/responses",
        json_body={
            "model": SAM_MODEL,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}, dict(video_part)],
                }
            ],
            "stream": stream,
            "metadata": {"include_confidence": "true"},
        },
    )


def upload_request(video_path: Path) -> MetaRequest:
    """The /files request that uploads a prepared video."""
    return MetaRequest("/files", upload=FileUpload(video_path, UPLOAD_PURPOSE))


def video_part(file_id: str) -> dict[str, str]:
    """The input part that points the request at an uploaded file."""
    return {"type": "input_video", "file_id": file_id}


# --- the perception ------------------------------------------------------------------------


class SamPerception:
    """Perception through SAM 3.1, over any Transport.

    Give it a live transport (wrapped in the budget guard) to really call Meta, or a
    ReplayTransport to answer from saved recordings with no key and no network. A video is
    uploaded once and its file id reused for every noun. Failures become PerceptionErrors
    with fixed messages; one raised before anything was sent is PerceptionNotSentError, so
    the budget does not count it as spent.
    """

    configured = True

    def __init__(
        self,
        transport: Transport,
        *,
        prompts: Mapping[str, str] = DEFAULT_PROMPTS,
        fps: float = DEFAULT_ANALYSIS_FPS,
    ) -> None:
        self._transport = transport
        self._prompts = dict(prompts)
        self._timebase_fps = fps
        self._file_ids: dict[Path, str] = {}

    def detect_and_track(self, video_path: Path, noun: str) -> list[Track]:
        """Tracks of every object matching `noun` in the prepared video, labelled `noun`."""
        path = Path(video_path)
        if not path.is_file():
            raise PerceptionNotSentError("The prepared video was not found.")
        prompt = self._prompts.get(noun, noun)
        file_id = self._uploaded(path)
        reply = self._send(sam_request(prompt, video_part(file_id)))
        detections = parse_sam_stream(reply, fps=self._timebase_fps)
        return tracks_from_detections(noun, detections)

    def _uploaded(self, path: Path) -> str:
        key = path.resolve()
        if key not in self._file_ids:
            self._file_ids[key] = _file_id(self._send(upload_request(path)))
        return self._file_ids[key]

    def _send(self, request: MetaRequest) -> str:
        try:
            reply = self._transport.send(request)
        except MissingApiKeyError:
            raise PerceptionNotSentError("No Meta API key is configured.") from None
        except MetaApiError as error:
            raise PerceptionError(
                f"The Meta API refused the request (HTTP {error.status})."
            ) from None
        except MetaConnectionError:
            raise PerceptionError("The Meta API could not be reached.") from None
        except RecordingNotFoundError:
            raise PerceptionError("No saved reply matches this request.") from None
        except RecordingCorruptError:
            raise PerceptionError("A saved reply could not be read.") from None
        except MetaError:
            raise PerceptionError("The Meta API call failed.") from None
        if not 200 <= reply.status < 300:
            raise PerceptionError(f"The Meta API answered HTTP {reply.status}.")
        return reply.body


def _file_id(body: str) -> str:
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = None
    file_id = parsed.get("id") if isinstance(parsed, dict) else None
    if not isinstance(file_id, str) or not file_id:
        raise PerceptionError("The upload reply has no file id.")
    return file_id
