"""SnapshotRenderer built on ffmpeg: take one frame of the working copy and draw the boxes.

One ffmpeg call selects the exact frame by its number (select=eq(n,FRAME)), draws the
person's box in a neutral grey and then the object's box in red (so red is never hidden
under grey) and writes a JPEG. The video is found by a function the caller supplies, from
the recording id; nothing from a request ever becomes a path here. Failures are OSErrors
whose messages quote nothing ffmpeg printed.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from pathlib import Path

from askfootage.adapters.media.ffmpeg import CommandRunner, run_command
from askfootage.ports.snapshots import SnapshotBox

OBJECT_COLOR = "red"
NEUTRAL_COLOR = "0x9aa0a6"
"""Grey for the person: it marks where they are without singling them out."""
OBJECT_THICKNESS = 6
PERSON_THICKNESS = 4
RENDER_TIMEOUT_SECONDS = 120.0

VideoFor = Callable[[str], Path | None]
"""The working copy of a recording, or None when there is none."""


class FfmpegSnapshotRenderer:
    """Draws boxes on one frame with ffmpeg."""

    def __init__(
        self,
        video_for: VideoFor,
        *,
        runner: CommandRunner = run_command,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._video_for = video_for
        self._runner = runner
        self._which = which

    def render(
        self, recording_id: str, frame: int, boxes: Sequence[SnapshotBox], destination: Path
    ) -> None:
        """Write frame number `frame` of the recording's working copy, boxes drawn, to a JPEG.

        Raises ValueError for a negative frame, FileNotFoundError when the recording has no
        working copy, and OSError when ffmpeg is missing or fails.
        """
        if isinstance(frame, bool) or frame < 0:
            raise ValueError("frame must be 0 or more")
        video = self._video_for(recording_id)
        if video is None or not Path(video).is_file():
            raise FileNotFoundError("the recording has no working copy")
        ffmpeg = self._which("ffmpeg")
        if not ffmpeg:
            raise OSError("ffmpeg was not found")
        args = [
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-protocol_whitelist", "file", "-i", str(video),
            "-vf", _filter(frame, boxes),
            "-frames:v", "1", "-fps_mode", "passthrough", "-q:v", "3",
            str(destination),
        ]  # fmt: skip
        try:
            result = self._runner(args, timeout=RENDER_TIMEOUT_SECONDS)
        except OSError:
            raise OSError("ffmpeg could not be started") from None
        if result.returncode != 0:
            raise OSError(f"ffmpeg failed to make the snapshot (exit code {result.returncode})")
        if not destination.is_file() or destination.stat().st_size == 0:
            raise OSError("ffmpeg made no snapshot")


def _filter(frame: int, boxes: Sequence[SnapshotBox]) -> str:
    # The person first, the object last, so the red box is on top.
    ordered = sorted(boxes, key=lambda box: box.role == "object")
    parts = [f"select=eq(n\\,{frame})"]
    parts.extend(_drawbox(box) for box in ordered)
    return ",".join(parts)


def _drawbox(box: SnapshotBox) -> str:
    x, y = max(0, round(box.x1)), max(0, round(box.y1))
    width = max(1, round(box.x2) - x)
    height = max(1, round(box.y2) - y)
    if box.role == "object":
        color, thickness = OBJECT_COLOR, OBJECT_THICKNESS
    else:
        color, thickness = NEUTRAL_COLOR, PERSON_THICKNESS
    return f"drawbox=x={x}:y={y}:w={width}:h={height}:color={color}:t={thickness}"
