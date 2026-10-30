"""Builders, a raw-SQL connection and JSON shapes shared by the tests in tests/db/.

Imported by name (tests/db is on sys.path while its tests run), so the module name is
unique across tests/. Every database lives in pytest's tmp_path; nothing touches data/.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, time
from pathlib import Path

from askfootage.ports.library_store import (
    Camera,
    Clip,
    Evidence,
    KeyFrame,
    Recording,
    RecordingStatus,
    SavedClip,
    Zone,
    ZonePoint,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "contract" / "examples"
DEMO_SEED = EXAMPLES_DIR / "demo-seed.json"

DAY = date(2026, 10, 29)
SQUARE: tuple[ZonePoint, ...] = ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9))


def camera(camera_id: str = "cam-1", name: str = "Front gate") -> Camera:
    """A camera with harmless defaults."""
    return Camera(id=camera_id, name=name)


def recording(
    recording_id: str = "rec-1",
    camera_id: str = "cam-1",
    day: date = DAY,
    start_time: time = time(10, 0, 0),
    length_seconds: int = 7200,
    status: RecordingStatus = "ready",
) -> Recording:
    """A recording with harmless defaults: cam-1, 29 Oct 2026, 10:00 for two hours."""
    return Recording(
        id=recording_id,
        camera=camera_id,
        day=day,
        start_time=start_time,
        length_seconds=length_seconds,
        status=status,
    )


def clip(
    clip_id: str = "clip-1",
    recording_id: str = "rec-1",
    day: date = DAY,
    start_time: time = time(10, 0, 5),
    start_seconds: int = 5,
    end_seconds: int = 20,
    *,
    evidence: tuple[Evidence, ...] = (Evidence("carrying", "Carrying · 15 s"),),
    zone: str | None = "Gate",
    key_frames: tuple[KeyFrame, ...] = (KeyFrame(5), KeyFrame(12, "frames/12.jpg")),
    thumbnail_url: str | None = None,
    label: str = "Person carrying a box",
) -> Clip:
    """A clip of rec-1 with harmless defaults."""
    return Clip(
        id=clip_id,
        recording_id=recording_id,
        day=day,
        start_time=start_time,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        label=label,
        evidence=evidence,
        zone=zone,
        why_matched="A person held a box while walking.",
        key_frames=key_frames,
        thumbnail_url=thumbnail_url,
    )


def zone(
    zone_id: str = "zone-1",
    camera_id: str = "cam-1",
    name: str = "Gate",
    points: tuple[ZonePoint, ...] = SQUARE,
) -> Zone:
    """A square zone on cam-1."""
    return Zone(id=zone_id, camera=camera_id, name=name, points=points)


@contextmanager
def raw_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """A plain sqlite3 connection with foreign keys on, in autocommit mode, closed after."""
    connection = sqlite3.connect(path, autocommit=True)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
    finally:
        connection.close()


def count_rows(path: Path, table: str) -> int:
    """Rows in one table. `table` must be one of the schema's own table names."""
    assert table in TABLES, table  # a fixed allow-list: never a value from a test input
    with raw_connection(path) as db:
        return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


TABLES = (
    "cameras",
    "recordings",
    "clips",
    "clip_evidence",
    "clip_key_frames",
    "zones",
    "zone_points",
    "saved_clips",
)
"""Every table in schema.sql."""


def clip_json(value: Clip) -> dict[str, object]:
    """A clip in the API's camelCase shape (contract/openapi.yaml, Clip)."""
    return {
        "id": value.id,
        "recordingId": value.recording_id,
        "day": value.day.isoformat(),
        "startTime": value.start_time.isoformat(),
        "startSeconds": value.start_seconds,
        "endSeconds": value.end_seconds,
        "label": value.label,
        "evidence": [{"kind": item.kind, "text": item.text} for item in value.evidence],
        "zone": value.zone,
        "whyMatched": value.why_matched,
        "keyFrames": [
            {"atSeconds": frame.at_seconds, "imageUrl": frame.image_url}
            for frame in value.key_frames
        ],
        "thumbnailUrl": value.thumbnail_url,
    }


def recording_json(value: Recording) -> dict[str, object]:
    """A recording in the API's camelCase shape (contract/openapi.yaml, Recording)."""
    return {
        "id": value.id,
        "day": value.day.isoformat(),
        "startTime": value.start_time.isoformat(),
        "lengthSeconds": value.length_seconds,
        "status": value.status,
    }


def zone_json(value: Zone) -> dict[str, object]:
    """A zone in the API's camelCase shape (contract/openapi.yaml, Zone)."""
    return {
        "id": value.id,
        "camera": value.camera,
        "name": value.name,
        "points": [[x, y] for x, y in value.points],
    }


def saved_clip_json(value: SavedClip) -> dict[str, object]:
    """A saved clip in the API's shape, savedAt in UTC ending in Z, whole seconds."""
    return {
        "id": value.id,
        "clip": clip_json(value.clip),
        "note": value.note,
        "savedAt": value.saved_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
