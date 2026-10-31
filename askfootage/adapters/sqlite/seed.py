"""Read the demo library (contract/examples/demo-seed.json) into validated dataclasses.

The file uses the API's camelCase JSON shapes. read_seed checks every field strictly
(required keys, JSON types, date and time formats) and builds the same frozen dataclasses
the library stores take, so a malformed file fails here, with a SeedDataError naming the
field at fault, before anything touches a database. seed_demo_data in store.py writes the
result in one transaction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from askfootage.ports.library_store import (
    Camera,
    Clip,
    Evidence,
    KeyFrame,
    Recording,
    Zone,
)

_DAY_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME_PATTERN = re.compile(r"\d{2}:\d{2}:\d{2}")


class SeedDataError(ValueError):
    """The demo seed is malformed or its rows break the library's rules.

    The message names the field or rule at fault and holds no file path.
    """


@dataclass(frozen=True, slots=True)
class SeedSavedClip:
    """A saved clip as the seed lists it: the clip is referred to by id."""

    id: str
    clip_id: str
    note: str
    saved_at: datetime


@dataclass(frozen=True, slots=True)
class DemoSeed:
    """Everything in a demo seed file, validated and in file order."""

    cameras: tuple[Camera, ...]
    recordings: tuple[Recording, ...]
    clips: tuple[Clip, ...]
    zones: tuple[Zone, ...]
    saved_clips: tuple[SeedSavedClip, ...]


def read_seed(seed_file: Path) -> DemoSeed:
    """Read and validate a demo seed file.

    Raises SeedDataError if the file is not UTF-8 JSON in the demo-seed shape; OSError
    (for example FileNotFoundError) if it cannot be read at all.
    """
    try:
        raw = json.loads(Path(seed_file).read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise SeedDataError("demo seed is not UTF-8 text") from None
    except json.JSONDecodeError as error:
        raise SeedDataError(f"demo seed is not valid JSON (line {error.lineno})") from None
    return parse_seed(raw)


def parse_seed(raw: object) -> DemoSeed:
    """Validate an already-decoded demo seed document and build its dataclasses.

    Keys the seed does not use (such as "today") are ignored; "savedClips" may be left
    out. Raises SeedDataError naming the first field at fault.
    """
    document = _object(raw, "demo seed")
    return DemoSeed(
        cameras=tuple(
            _camera(item, where)
            for item, where in _items(_field(document, "cameras", "demo seed"), "cameras")
        ),
        recordings=tuple(
            _recording(item, where)
            for item, where in _items(_field(document, "recordings", "demo seed"), "recordings")
        ),
        clips=tuple(
            _clip(item, where)
            for item, where in _items(_field(document, "clips", "demo seed"), "clips")
        ),
        zones=tuple(
            _zone(item, where)
            for item, where in _items(_field(document, "zones", "demo seed"), "zones")
        ),
        saved_clips=tuple(
            _saved_clip(item, where)
            for item, where in _items(document.get("savedClips", []), "savedClips")
        ),
    )


def _camera(raw: object, where: str) -> Camera:
    # Only these keys are read: a "password" key, or any other, is ignored and never stored.
    item = _object(raw, where)
    return _build(
        where,
        Camera,
        id=_text(item, "id", where),
        name=_text(item, "name", where),
        ip=_text(item, "ip", where),
        username=_text(item, "username", where),
        status=_text(item, "status", where),
        location=_optional_text(item, "location", where),
        department=_optional_text(item, "department", where),
        created_at=_aware_datetime(item, "createdAt", where),
    )


def _recording(raw: object, where: str) -> Recording:
    item = _object(raw, where)
    return _build(
        where,
        Recording,
        id=_text(item, "id", where),
        camera=_text(item, "camera", where),
        day=_day(item, "day", where),
        start_time=_time_of_day(item, "startTime", where),
        length_seconds=_whole(item, "lengthSeconds", where),
        status=_text(item, "status", where),
    )


def _clip(raw: object, where: str) -> Clip:
    item = _object(raw, where)
    evidence = tuple(
        _evidence(entry, entry_where)
        for entry, entry_where in _items(_field(item, "evidence", where), f"{where}.evidence")
    )
    key_frames = tuple(
        _key_frame(entry, entry_where)
        for entry, entry_where in _items(_field(item, "keyFrames", where), f"{where}.keyFrames")
    )
    return _build(
        where,
        Clip,
        id=_text(item, "id", where),
        recording_id=_text(item, "recordingId", where),
        day=_day(item, "day", where),
        start_time=_time_of_day(item, "startTime", where),
        start_seconds=_whole(item, "startSeconds", where),
        end_seconds=_whole(item, "endSeconds", where),
        label=_text(item, "label", where),
        evidence=evidence,
        zone=_optional_text(item, "zone", where),
        why_matched=_text(item, "whyMatched", where),
        key_frames=key_frames,
        thumbnail_url=_optional_text(item, "thumbnailUrl", where),
    )


def _evidence(raw: object, where: str) -> Evidence:
    item = _object(raw, where)
    return _build(where, Evidence, kind=_text(item, "kind", where), text=_text(item, "text", where))


def _key_frame(raw: object, where: str) -> KeyFrame:
    item = _object(raw, where)
    return _build(
        where,
        KeyFrame,
        at_seconds=_whole(item, "atSeconds", where),
        image_url=_optional_text(item, "imageUrl", where),
    )


def _zone(raw: object, where: str) -> Zone:
    item = _object(raw, where)
    points = tuple(
        _point(entry, entry_where)
        for entry, entry_where in _items(_field(item, "points", where), f"{where}.points")
    )
    return _build(
        where,
        Zone,
        id=_text(item, "id", where),
        camera=_text(item, "camera", where),
        name=_text(item, "name", where),
        points=points,
    )


def _point(raw: object, where: str) -> tuple[float, float]:
    if not isinstance(raw, list) or len(raw) != 2:
        raise SeedDataError(f"{where} must be a list of two numbers [x, y]")
    x, y = raw
    for value in (x, y):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise SeedDataError(f"{where} must be a list of two numbers [x, y]")
    return (float(x), float(y))


def _saved_clip(raw: object, where: str) -> SeedSavedClip:
    item = _object(raw, where)
    if "clipId" in item:
        clip_id = _text(item, "clipId", where)
    else:
        clip_id = _text(_object(_field(item, "clip", where), f"{where}.clip"), "id", where)
    saved_at = _aware_datetime(item, "savedAt", where)
    note = item.get("note", "")
    if not isinstance(note, str):
        raise SeedDataError(f"{where}.note must be a string")
    return SeedSavedClip(id=_text(item, "id", where), clip_id=clip_id, note=note, saved_at=saved_at)


def _build[T](where: str, factory: type[T], /, **values: object) -> T:
    """Construct a library dataclass, turning its validation error into a SeedDataError."""
    try:
        return factory(**values)
    except (ValueError, TypeError) as error:
        raise SeedDataError(f"{where}: {error}") from None


def _object(raw: object, where: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise SeedDataError(f"{where} must be a JSON object")
    return raw


def _items(raw: object, where: str) -> list[tuple[object, str]]:
    if not isinstance(raw, list):
        raise SeedDataError(f"{where} must be a JSON list")
    return [(item, f"{where}[{index}]") for index, item in enumerate(raw)]


def _field(item: dict[str, object], key: str, where: str) -> object:
    if key not in item:
        raise SeedDataError(f"{where} is missing {key!r}")
    return item[key]


def _text(item: dict[str, object], key: str, where: str) -> str:
    value = _field(item, key, where)
    if not isinstance(value, str):
        raise SeedDataError(f"{where}.{key} must be a string")
    return value


def _optional_text(item: dict[str, object], key: str, where: str) -> str | None:
    value = _field(item, key, where)
    if value is not None and not isinstance(value, str):
        raise SeedDataError(f"{where}.{key} must be a string or null")
    return value


def _whole(item: dict[str, object], key: str, where: str) -> int:
    value = _field(item, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SeedDataError(f"{where}.{key} must be a whole number")
    return value


def _day(item: dict[str, object], key: str, where: str) -> date:
    value = _text(item, key, where)
    try:
        if not _DAY_PATTERN.fullmatch(value):
            raise ValueError(value)
        return date.fromisoformat(value)
    except ValueError:
        raise SeedDataError(f"{where}.{key} must be a date written YYYY-MM-DD") from None


def _aware_datetime(item: dict[str, object], key: str, where: str) -> datetime:
    value = _text(item, key, where)
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise SeedDataError(f"{where}.{key} must be an ISO 8601 date-time") from None
    if moment.tzinfo is None:
        raise SeedDataError(f"{where}.{key} must include a time zone, such as Z")
    return moment


def _time_of_day(item: dict[str, object], key: str, where: str) -> time:
    value = _text(item, key, where)
    try:
        if not _TIME_PATTERN.fullmatch(value):
            raise ValueError(value)
        return time.fromisoformat(value)
    except ValueError:
        raise SeedDataError(f"{where}.{key} must be a time of day written HH:MM:SS") from None
