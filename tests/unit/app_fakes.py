"""Fakes for the ingest, add-concept and evaluate tests: no disk video, network or Meta."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint
from askfootage.ports.perception import PerceptionError
from askfootage.ports.video_store import PreparedVideo, VideoPreparationError


def track(track_id: int, label: str, frames: Sequence[int], x0: float = 0.0) -> Track:
    """A 40 x 100 box sliding right 2 px per frame."""
    boxes = ((x0 + 2 * i, x0 + 2 * i + 40) for i in range(len(frames)))
    points = tuple(
        TrackPoint(f, BoundingBox(left, 0, right, 100))
        for f, (left, right) in zip(frames, boxes, strict=True)
    )
    return Track(track_id, label, points)


class ScriptedPerception:
    """Perception that returns the given tracks per noun and records every call."""

    def __init__(self, tracks: dict[str, list[Track]], fail_on: Sequence[str] = ()) -> None:
        self.tracks = tracks
        self.fail_on = set(fail_on)
        self.calls: list[tuple[Path, str]] = []

    def detect_and_track(self, video_path: Path, noun: str) -> list[Track]:
        self.calls.append((video_path, noun))
        if noun in self.fail_on:
            raise PerceptionError("boom with secret C:\\path")
        return list(self.tracks.get(noun, []))


class FakePreparer:
    """VideoPreparer that writes a stub prepared.mp4 and counts calls."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def prepare(self, source: Path, dest_dir: Path) -> PreparedVideo:
        self.calls += 1
        if self.fail:
            raise VideoPreparationError("The video could not be read.")
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / "prepared.mp4"
        out.write_bytes(b"stub")
        return PreparedVideo(out, 5.0, 10.0, 50)


class MemoryTracks:
    """TrackStore in memory."""

    def __init__(self) -> None:
        self.saved: dict[tuple[str, str], list[Track]] = {}
        self.saves: list[tuple[str, str]] = []

    def save_tracks(self, video_id: str, concept: str, tracks: Sequence[Track]) -> None:
        self.saved[(video_id, concept)] = list(tracks)
        self.saves.append((video_id, concept))

    def tracks_for(self, video_id: str, label: str) -> list[Track]:
        return list(self.saved.get((video_id, label), []))

    def delete_video(self, video_id: str) -> int:
        keys = [k for k in self.saved if k[0] == video_id]
        for k in keys:
            del self.saved[k]
        return len(keys)
