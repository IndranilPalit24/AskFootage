"""Hand-made labels for the real clips, in seconds (format in labels/README.md).

This is the second labels format. The frame-based one in application/evaluate.py scores
relation intervals; this one records only what a person actually said about a clip, and
marks anything they did not confirm as "unconfirmed" so it is never scored as truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from askfootage.application.errors import InvalidInputError, NotFoundError

EVENT_TYPES = ("in_frame", "carrying", "leaves_room")
STATUSES = ("confirmed", "unconfirmed")
_EVENT_FIELDS = {"type", "object", "start_s", "end_s", "status"}
MAX_SECONDS = 360_000.0


@dataclass(frozen=True, slots=True)
class ClipEvent:
    """One thing that happened in a clip, between two times in seconds (ends included)."""

    type: str
    object: str
    start_s: float
    end_s: float
    status: str


@dataclass(frozen=True, slots=True)
class ClipLabels:
    clip: str
    events: tuple[ClipEvent, ...]

    def has_confirmed(self, event_type: str) -> bool:
        """True when a person confirmed an event of this type (unconfirmed ones do not count)."""
        return any(e.type == event_type and e.status == "confirmed" for e in self.events)


def _bad(field_name: str, problem: str) -> InvalidInputError:
    return InvalidInputError(field_name, problem)


def _seconds(entry: dict[str, object], name: str) -> float:
    value = entry.get(name)
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not 0 <= value <= MAX_SECONDS
    ):
        raise _bad(name, f"must be a number of seconds, 0 to {MAX_SECONDS:g}")
    return float(value)


def _event(entry: object) -> ClipEvent:
    if not isinstance(entry, dict):
        raise _bad("events", "each entry must be an object")
    if set(entry) != _EVENT_FIELDS:
        raise _bad("events", f"each entry needs exactly: {', '.join(sorted(_EVENT_FIELDS))}")
    if entry["type"] not in EVENT_TYPES:
        raise _bad("type", f"must be one of {', '.join(EVENT_TYPES)}")
    if entry["status"] not in STATUSES:
        raise _bad("status", f"must be one of {', '.join(STATUSES)}")
    obj = entry["object"]
    if not isinstance(obj, str) or not obj.strip():
        raise _bad("object", "must be a non-empty string")
    start, end = _seconds(entry, "start_s"), _seconds(entry, "end_s")
    if end < start:
        raise _bad("end_s", "must not be before start_s")
    return ClipEvent(entry["type"], obj.strip(), start, end, entry["status"])


def load_clip_labels(path: Path) -> ClipLabels:
    """Read and check one seconds-based labels file.

    Raises NotFoundError when the file is missing and InvalidInputError (naming the field,
    never echoing file text) when it is not valid JSON or breaks the format.
    """
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise NotFoundError("The labels file was not found.") from None
    except OSError:
        raise _bad("labels", "the file could not be read") from None
    try:
        data = json.loads(text)
    except ValueError:
        raise _bad("labels", "the file is not valid JSON") from None
    if not isinstance(data, dict) or set(data) != {"clip", "events"}:
        raise _bad("labels", "the file must be an object with exactly: clip, events")
    clip = data["clip"]
    if not isinstance(clip, str) or not clip.strip():
        raise _bad("clip", "must be a non-empty string")
    if not isinstance(data["events"], list):
        raise _bad("events", "must be a list")
    return ClipLabels(clip.strip(), tuple(_event(entry) for entry in data["events"]))
