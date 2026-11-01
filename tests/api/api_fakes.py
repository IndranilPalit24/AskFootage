"""In-memory fakes of the five library Protocols, seeded from contract/examples/demo-seed.json.

They follow the conventions in askfootage/ports/library_store.py: lookups return None or
False, lists come back in the documented order, and writes raise DuplicateError or
MissingReferenceError. Cameras get sequential ids that are never reused, names that are
unique ignoring case (str.casefold), and a delete that takes the camera's recordings,
clips, saved clips and zones with it. test_api_fake_store_agreement.py checks that the
real SQLite store behaves the same. No disk, no network.

The indexing fakes (track store, preparer, perception, file layout) follow the ports in
askfootage/ports/track_store.py, perception.py and video_store.py, and record every call
so tests can check the order things happened in.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path, PurePosixPath
from typing import Any

from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint
from askfootage.ports.library_store import (
    Camera,
    CameraCounts,
    CameraStatus,
    Clip,
    DaySummary,
    DuplicateError,
    Evidence,
    KeyFrame,
    MissingReferenceError,
    NewCamera,
    Recording,
    RecordingStatus,
    SavedClip,
    Zone,
    camera_id_for,
    camera_number,
)
from askfootage.ports.video_store import PreparedVideo

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
    return Camera(
        id=data["id"],
        name=data["name"],
        ip=data["ip"],
        username=data["username"],
        status=data["status"],
        location=data["location"],
        department=data["department"],
        created_at=datetime.fromisoformat(data["createdAt"]),
    )


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
    """A Clip from its contract JSON (any camera field is ignored: it is the recording's)."""
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
    """One object implementing the CameraStore, RecordingStore, ClipStore, ZoneStore and
    SavedClipStore Protocols."""

    def __init__(self) -> None:
        self.cameras: dict[str, Camera] = {}
        self.recordings: dict[str, Recording] = {}
        self.clips: dict[str, Clip] = {}
        self.zones: dict[str, Zone] = {}
        self.saved: dict[str, SavedClip] = {}
        self.last_camera_number = 0
        """The highest camera number ever handed out; numbers are never reused."""
        self.status_log: list[tuple[str, RecordingStatus, str | None]] = []
        """Every status change set_recording_status made: (recording id, status, note)."""

    @classmethod
    def from_seed(cls, seed_file: Path = SEED_FILE) -> InMemoryLibrary:
        """A library holding the whole demo dataset."""
        seed = json.loads(seed_file.read_text(encoding="utf-8"))
        library = cls()
        for camera in seed["cameras"]:
            library.put_camera(camera_from_json(camera))
        for recording in seed["recordings"]:
            library.add_recording(recording_from_json(recording))
        for clip in seed["clips"]:
            library.add_clip(clip_from_json(clip))
        for zone in seed["zones"]:
            library.add_zone(zone_from_json(zone))
        for saved in seed.get("savedClips", []):
            library.add_saved_clip(
                saved["id"],
                saved["clipId"],
                saved["note"],
                datetime.fromisoformat(saved["savedAt"]),
            )
        return library

    def put_camera(self, camera: Camera) -> None:
        """Store a camera that already has its id (seeding only), keeping the sequence."""
        if camera.id in self.cameras or self._camera_name_used(camera.name):
            raise DuplicateError("camera id or name taken")
        self.cameras[camera.id] = camera
        self.last_camera_number = max(self.last_camera_number, camera_number(camera.id))

    # --- CameraStore ------------------------------------------------------------------------

    def list_cameras(self) -> list[Camera]:
        return sorted(self.cameras.values(), key=lambda camera: camera_number(camera.id))

    def get_camera(self, camera_id: str) -> Camera | None:
        return self.cameras.get(camera_id)

    def add_camera(self, camera: NewCamera) -> Camera:
        if self._camera_name_used(camera.name):
            raise DuplicateError("camera name taken")
        self.last_camera_number += 1
        stored = Camera(
            id=camera_id_for(self.last_camera_number),
            name=camera.name,
            ip=camera.ip,
            username=camera.username,
            status=camera.status,
            location=camera.location,
            department=camera.department,
            created_at=camera.created_at,
        )
        self.cameras[stored.id] = stored
        return stored

    def set_camera_status(self, camera_id: str, status: CameraStatus) -> Camera | None:
        camera = self.cameras.get(camera_id)
        if camera is None:
            return None
        self.cameras[camera_id] = replace(camera, status=status)
        return self.cameras[camera_id]

    def delete_camera(self, camera_id: str) -> bool:
        if self.cameras.pop(camera_id, None) is None:
            return False
        gone_recordings = {r.id for r in self.recordings.values() if r.camera == camera_id}
        gone_clips = {c.id for c in self.clips.values() if c.recording_id in gone_recordings}
        self.saved = {k: s for k, s in self.saved.items() if s.clip.id not in gone_clips}
        self.clips = {k: c for k, c in self.clips.items() if k not in gone_clips}
        self.recordings = {k: r for k, r in self.recordings.items() if k not in gone_recordings}
        self.zones = {k: z for k, z in self.zones.items() if z.camera != camera_id}
        return True

    def camera_counts(self) -> dict[str, CameraCounts]:
        counts = {camera_id: [0, 0, 0] for camera_id in self.cameras}
        for recording in self.recordings.values():
            counts[recording.camera][0] += 1
        for zone in self.zones.values():
            counts[zone.camera][1] += 1
        for saved in self.saved.values():
            counts[self.recordings[saved.clip.recording_id].camera][2] += 1
        return {
            camera_id: CameraCounts(recordings=r, zones=z, saved_clips=s)
            for camera_id, (r, z, s) in counts.items()
        }

    def _camera_name_used(self, name: str) -> bool:
        wanted = name.casefold()
        return any(camera.name.casefold() == wanted for camera in self.cameras.values())

    # --- RecordingStore ---------------------------------------------------------------------

    def summarise_days(
        self, camera_id: str | None, first_day: date, last_day: date
    ) -> list[DaySummary]:
        counts: dict[date, list[int]] = {}
        for recording in self.recordings.values():
            if camera_id not in (None, recording.camera):
                continue
            if first_day <= recording.day <= last_day:
                count = counts.setdefault(recording.day, [0, 0])
                count[0] += 1
                count[1] += recording.status == "ready"
        return [DaySummary(day, total, ready) for day, (total, ready) in sorted(counts.items())]

    def list_recordings(self, camera_id: str | None, day: date) -> list[Recording]:
        found = [
            r for r in self.recordings.values() if camera_id in (None, r.camera) and r.day == day
        ]
        return sorted(found, key=lambda r: (r.start_time, r.camera, r.id))

    def get_recording(self, recording_id: str) -> Recording | None:
        return self.recordings.get(recording_id)

    def add_recording(self, recording: Recording) -> None:
        if recording.id in self.recordings:
            raise DuplicateError("recording id taken")
        if recording.camera not in self.cameras:
            raise MissingReferenceError("no such camera")
        self.recordings[recording.id] = recording

    def set_recording_status(
        self,
        recording_id: str,
        status: RecordingStatus,
        *,
        expected: RecordingStatus | None = None,
        note: str | None = None,
    ) -> Recording | None:
        recording = self.recordings.get(recording_id)
        if recording is None or (expected is not None and recording.status != expected):
            return None
        updated = replace(recording, status=status, status_note=note)
        self.recordings[recording_id] = updated
        self.status_log.append((recording_id, status, note))
        return updated

    # --- ClipStore --------------------------------------------------------------------------

    def list_clips(self, camera_id: str | None, day: date) -> list[Clip]:
        found = [
            clip
            for clip in self.clips.values()
            if clip.day == day and camera_id in (None, self.recordings[clip.recording_id].camera)
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


_STORE_CALL_PREFIXES = (
    "list_",
    "get_",
    "summarise_",
    "add_",
    "replace_",
    "update_",
    "set_",
    "delete_",
    "camera_counts",
)


class ExplodingLibrary(InMemoryLibrary):
    """Every store call fails with an exception whose text holds a path and a secret."""

    def __init__(self, secret: str) -> None:
        super().__init__()
        self.secret = secret

    def __getattribute__(self, name: str) -> Any:
        attribute = super().__getattribute__(name)
        if name.startswith(_STORE_CALL_PREFIXES):
            secret = super().__getattribute__("secret")

            def explode(*args: object, **kwargs: object) -> Any:
                raise RuntimeError(
                    f"database locked at C:\\Users\\someone\\data\\demo.sqlite key={secret}"
                )

            return explode
        return attribute


# --- Indexing fakes ---------------------------------------------------------------------------

FAKE_SERVER_ROOT = PurePosixPath("/srv/askfootage/private-data")
"""A made-up server folder: it must never show up in a response or a status note."""


def make_track(track_id: int, label: str, frames: Sequence[int]) -> Track:
    """A track with a 10 x 10 box on each frame, sliding right one pixel per frame."""
    points = tuple(
        TrackPoint(frame=frame, box=BoundingBox(frame, 0.0, frame + 10.0, 10.0)) for frame in frames
    )
    return Track(track_id=track_id, label=label, points=points)


class InMemoryTrackStore:
    """The TrackStore Protocol in memory, refusing what the port says it refuses."""

    def __init__(self, library: InMemoryLibrary) -> None:
        self.library = library
        self.saved: dict[tuple[str, str], tuple[Track, ...]] = {}
        self.calls: list[tuple[str, str]] = []
        """(video id, concept) for every save_tracks call that wrote."""

    def save_tracks(self, video_id: str, concept: str, tracks: Sequence[Track]) -> None:
        if any(track.label != concept for track in tracks):
            raise ValueError("every track's label must equal the concept")
        if len({track.track_id for track in tracks}) != len(tracks):
            raise ValueError("track ids must be unique")
        if video_id not in self.library.recordings:
            raise MissingReferenceError("no such video")
        self.saved[(video_id, concept)] = tuple(tracks)
        self.calls.append((video_id, concept))

    def tracks_for(self, video_id: str, label: str) -> list[Track]:
        return sorted(self.saved.get((video_id, label), ()), key=lambda track: track.track_id)

    def concept_done(self, video_id: str, concept: str) -> bool:
        """True once the concept was saved for the video, even with no tracks (ran, empty)."""
        return (video_id, concept) in self.saved

    def delete_video(self, video_id: str) -> int:
        gone = [key for key in self.saved if key[0] == video_id]
        count = sum(len(self.saved.pop(key)) for key in gone)
        return count


class FakeLayout:
    """The VideoFileLayout Protocol under FAKE_SERVER_ROOT. Pure paths: nothing is created."""

    def __init__(self, root: PurePosixPath = FAKE_SERVER_ROOT) -> None:
        self.root = root

    def video_dir(self, video_id: str) -> Path:
        return Path(self.root / "videos" / video_id)

    def raw_dir(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "raw"

    def prepared_path(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "prepared.mp4"


class FakePreparer:
    """The VideoPreparer Protocol: describes a 5 fps working copy, or raises `error`."""

    def __init__(self, error: Exception | None = None, fps: float = 5.0) -> None:
        self.error = error
        self.fps = fps
        self.calls: list[tuple[Path, Path]] = []
        self.on_prepare: list[Any] = []
        """Callables run inside prepare(), to change the store mid-run."""

    def prepare(self, source: Path, dest_dir: Path) -> PreparedVideo:
        self.calls.append((source, dest_dir))
        for hook in self.on_prepare:
            hook()
        if self.error is not None:
            raise self.error
        return PreparedVideo(
            path=dest_dir / "prepared.mp4", fps=self.fps, duration_seconds=60.0, frame_count=300
        )


class FakePerception:
    """The Perception Protocol: the given tracks per noun, or `error` for the nouns listed."""

    def __init__(
        self,
        tracks: dict[str, list[Track]] | None = None,
        error: Exception | None = None,
        fail_on: Sequence[str] = (),
    ) -> None:
        self.tracks = tracks or {}
        self.error = error
        self.fail_on = set(fail_on)
        self.calls: list[tuple[Path, str]] = []

    def detect_and_track(self, video_path: Path, noun: str) -> list[Track]:
        self.calls.append((video_path, noun))
        if self.error is not None and (not self.fail_on or noun in self.fail_on):
            raise self.error
        return list(self.tracks.get(noun, []))
