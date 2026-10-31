"""A fake perception and video preparer for trying the command-line tools without a key.

DemoPerception returns the same deterministic scene for any video: a person walking right
and, for every other noun, one object moving with them (so the carrying rule fires). It
makes no network call and reads no file. CopyPreparer "prepares" a video by copying it
(atomically) and reports a default 640 x 360 frame size.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint
from askfootage.ports.video_store import PreparedVideo, VideoPreparationError

DEMO_FRAMES = 60
DEMO_FPS = 5.0
DEMO_WIDTH = 640
DEMO_HEIGHT = 360
"""The frame size the demo tracks are drawn for, which the copy preparer reports."""
PERSON_NOUN = "person"


class DemoPerception:
    """Perception that invents the same tracks for every video."""

    def detect_and_track(self, video_path: Path, noun: str) -> list[Track]:
        """One track per call: the person, or an object carried along with them."""
        points = []
        for frame in range(DEMO_FRAMES):
            x = 20.0 + 4.0 * frame
            if noun.strip().lower() == PERSON_NOUN:
                box = BoundingBox(x, 100.0, x + 40.0, 200.0)
            else:
                box = BoundingBox(x + 25.0, 110.0, x + 45.0, 130.0)
            points.append(TrackPoint(frame, box))
        return [Track(1, noun, tuple(points))]


class CopyPreparer:
    """VideoPreparer that copies the source to dest_dir/prepared.mp4 (no ffmpeg needed)."""

    def prepare(self, source: Path, dest_dir: Path) -> PreparedVideo:
        """Copy the file; VideoPreparationError when the source is missing."""
        if not Path(source).is_file():
            raise VideoPreparationError("The source video was not found.")
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / "prepared.mp4"
        descriptor, temp_name = tempfile.mkstemp(dir=dest_dir, prefix="prepared-", suffix=".tmp")
        os.close(descriptor)
        try:
            shutil.copyfile(source, temp_name)
            os.replace(temp_name, out)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        return PreparedVideo(
            out, DEMO_FPS, DEMO_FRAMES / DEMO_FPS, DEMO_FRAMES, DEMO_WIDTH, DEMO_HEIGHT
        )
