"""Builders, a raw-SQL connection and JSON shapes shared by the tests in tests/db/.

Imported by name (tests/db is on sys.path while its tests run), so the module name is
unique across tests/. Every database lives in pytest's tmp_path; nothing touches data/.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time
from pathlib import Path

from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint
from askfootage.ports.library_store import (
    Camera,
    CameraStatus,
    Clip,
    Evidence,
    KeyFrame,
    NewCamera,
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
CREATED_AT = datetime(2026, 10, 30, 9, 0, 0, tzinfo=UTC)

CAM_1 = "CAM-001"
"""The first camera an empty library hands out."""
CAM_2 = "CAM-002"
"""The second camera an empty library hands out."""
NO_SUCH_CAMERA = "CAM-009"
"""A well-formed camera id that no test fixture creates."""


def new_camera(
    name: str = "Front gate",
    *,
    ip: str = "192.168.1.10",
    username: str = "viewer",
    status: CameraStatus = "online",
    location: str | None = None,
    department: str | None = None,
    created_at: datetime = CREATED_AT,
) -> NewCamera:
    """What add_camera takes, with harmless defaults; the store gives out the id."""
    return NewCamera(
        name=name,
        ip=ip,
        username=username,
        status=status,
        location=location,
        department=department,
        created_at=created_at,
    )


def stored_camera(camera_id: str, camera: NewCamera) -> Camera:
    """The Camera the store should return for `camera` stored under `camera_id`."""
    return Camera(
        id=camera_id,
        name=camera.name,
        ip=camera.ip,
        username=camera.username,
        status=camera.status,
        location=camera.location,
        department=camera.department,
        created_at=camera.created_at,
    )


def recording(
    recording_id: str = "rec-1",
    camera_id: str = CAM_1,
    day: date = DAY,
    start_time: time = time(10, 0, 0),
    length_seconds: int = 7200,
    status: RecordingStatus = "ready",
    *,
    status_note: str | None = None,
) -> Recording:
    """A recording with harmless defaults: CAM-001, 29 Oct 2026, 10:00 for two hours."""
    return Recording(
        id=recording_id,
        camera=camera_id,
        day=day,
        start_time=start_time,
        length_seconds=length_seconds,
        status=status,
        status_note=status_note,
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
    camera_id: str = CAM_1,
    name: str = "Gate",
    points: tuple[ZonePoint, ...] = SQUARE,
) -> Zone:
    """A square zone on CAM-001."""
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
    "camera_sequence",
    "cameras",
    "recordings",
    "clips",
    "clip_evidence",
    "clip_key_frames",
    "zones",
    "zone_points",
    "saved_clips",
    "tracks",
    "track_points",
    "concepts_searched",
)
"""Every table in schema.sql."""


def track(
    track_id: int = 1,
    label: str = "person",
    frames: tuple[int, ...] = (0, 1, 2),
    *,
    box: BoundingBox | None = None,
) -> Track:
    """A track with one point per frame; boxes drift right by 1.25 px per frame unless
    `box` fixes them all."""
    return Track(
        track_id=track_id,
        label=label,
        points=tuple(
            TrackPoint(frame, box or BoundingBox(10.5 + frame * 1.25, 20.0, 50.75 + frame, 90.0))
            for frame in frames
        ),
    )


def clip_json(value: Clip) -> dict[str, object]:
    """A clip in the demo seed's camelCase shape: the API's Clip without its camera."""
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


def api_clip_json(value: Clip, camera_id: str) -> dict[str, object]:
    """A clip in the API's shape (contract/openapi.yaml, Clip): its recording's camera too."""
    # snapshotUrl is made by the API from its snapshot store; it is never stored.
    return {**clip_json(value), "camera": camera_id, "snapshotUrl": None}


def recording_json(value: Recording) -> dict[str, object]:
    """A recording in the API's camelCase shape (contract/openapi.yaml, Recording)."""
    return {
        "id": value.id,
        "camera": value.camera,
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


def saved_clip_json(value: SavedClip, camera_id: str) -> dict[str, object]:
    """A saved clip in the API's shape, savedAt in UTC ending in Z, whole seconds."""
    return {
        "id": value.id,
        "clip": api_clip_json(value.clip, camera_id),
        "note": value.note,
        "savedAt": value.saved_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def camera_json(value: Camera) -> dict[str, object]:
    """The fields of the API's Camera (contract/openapi.yaml) that the store holds itself.

    The API adds rtspUrlMasked (built from username and ip) and the three counts.
    """
    return {
        "id": value.id,
        "name": value.name,
        "location": value.location,
        "department": value.department,
        "ip": value.ip,
        "status": value.status,
        "createdAt": value.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
