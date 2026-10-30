"""In-memory fakes of the four library Protocols, seeded from contract/examples/demo-seed.json.

They follow the conventions in askfootage/ports/library_store.py: lookups return None or
False, lists come back in the documented order, and writes raise DuplicateError or
MissingReferenceError. No disk, no network.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from askfootage.ports.library_store import (
    Camera,
    Clip,
    DaySummary,
    DuplicateError,
    Evidence,
    KeyFrame,
    MissingReferenceError,
    Recording,
    SavedClip,
    Zone,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = REPO_ROOT / "contract"
EXAMPLES_DIR = CONTRACT_DIR / "examples"
SEED_FILE = EXAMPLES_DIR / "demo-seed.json"

# The first 8 bytes are what an MP4 starts with: a box size, then the "ftyp" box type.
FAKE_MP4 = (
    b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + bytes(range(256)) * 4 + b"end-of-video"
)


def load_example(name: str) -> Any:
    """A JSON file from contract/examples."""
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


def camera_from_json(data: dict[str, Any]) -> Camera:
    """A Camera from its seed JSON."""
    return Camera(id=data["id"], name=data["name"])


def recording_from_json(data: dict[str, Any]) -> Recording:
    """A Recording from its seed JSON."""
    return Recording(
        id=data["id"],
        camera=data["camera"],
        day=date.fromisoformat(data["day"]),
        start_time=time.fromisoformat(data["startTime"]),
        length_seconds=data["lengthSeconds"],
        status=data["status"],
    )


def clip_from_json(data: dict[str, Any]) -> Clip:
    """A Clip from its contract JSON."""
    return Clip(
        id=data["id"],
        recording_id=data["recordingId"],
        day=date.fromisoformat(data["day"]),
        start_time=time.fromisoformat(data["startTime"]),
        start_seconds=data["startSeconds"],
        end_seconds=data["endSeconds"],
        label=data["label"],
        evidence=tuple(Evidence(kind=item["kind"], text=item["text"]) for item in data["evidence"]),
        zone=data["zone"],
        why_matched=data["whyMatched"],
        key_frames=tuple(
            KeyFrame(at_seconds=frame["atSeconds"], image_url=frame["imageUrl"])
            for frame in data["keyFrames"]
        ),
        thumbnail_url=data["thumbnailUrl"],
    )


def zone_from_json(data: dict[str, Any]) -> Zone:
    """A Zone from its contract JSON."""
    return Zone(
        id=data["id"],
        camera=data["camera"],
        name=data["name"],
        points=tuple((float(x), float(y)) for x, y in data["points"]),
    )


class InMemoryLibrary:
    """One object implementing RecordingStore, ClipStore, ZoneStore and SavedClipStore."""

    def __init__(self) -> None:
        self.cameras: dict[str, Camera] = {}
        self.recordings: dict[str, Recording] = {}
        self.clips: dict[str, Clip] = {}
        self.zones: dict[str, Zone] = {}
        self.saved: dict[str, SavedClip] = {}

    @classmethod
    def from_seed(cls, seed_file: Path = SEED_FILE) -> InMemoryLibrary:
        """A library holding the whole demo dataset."""
        seed = json.loads(seed_file.read_text(encoding="utf-8"))
        library = cls()
        for camera in seed["cameras"]:
            library.cameras[camera["id"]] = camera_from_json(camera)
        for recording in seed["recordings"]:
            library.add_recording(recording_from_json(recording))
        for clip in seed["clips"]:
            library.add_clip(clip_from_json(clip))
        for zone in seed["zones"]:
            library.add_zone(zone_from_json(zone))
        return library

    # --- RecordingStore ---------------------------------------------------------------------

    def list_cameras(self) -> list[Camera]:
        return sorted(self.cameras.values(), key=lambda camera: camera.id)

    def get_camera(self, camera_id: str) -> Camera | None:
        return self.cameras.get(camera_id)

    def summarise_days(self, camera_id: str, first_day: date, last_day: date) -> list[DaySummary]:
        counts: dict[date, list[int]] = {}
        for recording in self.recordings.values():
            if recording.camera == camera_id and first_day <= recording.day <= last_day:
                count = counts.setdefault(recording.day, [0, 0])
                count[0] += 1
                count[1] += recording.status == "ready"
        return [DaySummary(day, total, ready) for day, (total, ready) in sorted(counts.items())]

    def list_recordings(self, camera_id: str, day: date) -> list[Recording]:
        found = [r for r in self.recordings.values() if r.camera == camera_id and r.day == day]
        return sorted(found, key=lambda recording: (recording.start_time, recording.id))

    def get_recording(self, recording_id: str) -> Recording | None:
        return self.recordings.get(recording_id)

    def add_recording(self, recording: Recording) -> None:
        if recording.id in self.recordings:
            raise DuplicateError("recording id taken")
        if recording.camera not in self.cameras:
            raise MissingReferenceError("no such camera")
        self.recordings[recording.id] = recording

    # --- ClipStore --------------------------------------------------------------------------

    def list_clips(self, camera_id: str, day: date) -> list[Clip]:
        found = [
            clip
            for clip in self.clips.values()
            if clip.day == day and self.recordings[clip.recording_id].camera == camera_id
        ]
        return sorted(found, key=lambda clip: (clip.start_time, clip.id))

    def get_clip(self, clip_id: str) -> Clip | None:
        return self.clips.get(clip_id)

    def add_clip(self, clip: Clip) -> None:
        if clip.id in self.clips:
            raise DuplicateError("clip id taken")
        if clip.recording_id not in self.recordings:
            raise MissingReferenceError("no such recording")
        self.clips[clip.id] = clip

    # --- ZoneStore --------------------------------------------------------------------------

    def list_zones(self, camera_id: str | None = None) -> list[Zone]:
        found = [z for z in self.zones.values() if camera_id is None or z.camera == camera_id]
        return sorted(found, key=lambda zone: (zone.name, zone.id))

    def get_zone(self, zone_id: str) -> Zone | None:
        return self.zones.get(zone_id)

    def add_zone(self, zone: Zone) -> None:
        if zone.id in self.zones or self._name_used(zone):
            raise DuplicateError("zone id or name taken")
        if zone.camera not in self.cameras:
            raise MissingReferenceError("no such camera")
        self.zones[zone.id] = zone

    def replace_zone(self, zone: Zone) -> bool:
        existing = self.zones.get(zone.id)
        if existing is None:
            return False
        if self._name_used(replace(zone, camera=existing.camera)):
            raise DuplicateError("zone name taken")
        self.zones[zone.id] = replace(zone, camera=existing.camera)
        return True

    def delete_zone(self, zone_id: str) -> bool:
        return self.zones.pop(zone_id, None) is not None

    def _name_used(self, zone: Zone) -> bool:
        """Whether another zone on the camera has this name, ignoring case (as the port says)."""
        wanted = zone.name.casefold()
        return any(
            other.camera == zone.camera and other.name.casefold() == wanted and other.id != zone.id
            for other in self.zones.values()
        )

    # --- SavedClipStore ---------------------------------------------------------------------

    def list_saved_clips(self, day: date | None = None) -> list[SavedClip]:
        found = [s for s in self.saved.values() if day is None or s.clip.day == day]
        found.sort(key=lambda saved: saved.id)
        found.sort(key=lambda saved: saved.saved_at, reverse=True)
        return found

    def get_saved_clip(self, saved_id: str) -> SavedClip | None:
        return self.saved.get(saved_id)

    def add_saved_clip(
        self, saved_id: str, clip_id: str, note: str, saved_at: datetime
    ) -> SavedClip:
        clip = self.clips.get(clip_id)
        if clip is None:
            raise MissingReferenceError("no such clip")
        if saved_id in self.saved or any(s.clip.id == clip_id for s in self.saved.values()):
            raise DuplicateError("saved id taken or clip already saved")
        saved = SavedClip(id=saved_id, clip=clip, note=note, saved_at=saved_at)
        self.saved[saved_id] = saved
        return saved

    def update_note(self, saved_id: str, note: str) -> SavedClip | None:
        saved = self.saved.get(saved_id)
        if saved is None:
            return None
        self.saved[saved_id] = replace(saved, note=note)
        return self.saved[saved_id]

    def delete_saved_clip(self, saved_id: str) -> bool:
        return self.saved.pop(saved_id, None) is not None


class ExplodingLibrary(InMemoryLibrary):
    """Every store call fails with an exception whose text holds a path and a secret."""

    def __init__(self, secret: str) -> None:
        super().__init__()
        self.secret = secret

    def __getattribute__(self, name: str) -> Any:
        attribute = super().__getattribute__(name)
        if name.startswith(("list_", "get_", "summarise_", "add_", "replace_", "update_")) or (
            name.startswith("delete_")
        ):
            secret = super().__getattribute__("secret")

            def explode(*args: object, **kwargs: object) -> Any:
                raise RuntimeError(
                    f"database locked at C:\\Users\\someone\\data\\demo.sqlite key={secret}"
                )

            return explode
        return attribute
