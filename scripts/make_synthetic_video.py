r"""Make a short synthetic MP4 for offline tests: a 'person' carrying an object into a region.

    .venv\Scripts\python.exe scripts\make_synthetic_video.py data\synthetic.mp4 [--force]

A red disc (the person) walks from the left edge into a shaded rectangle (the region) while
a yellow square (the object) moves with it. Frames are drawn with numpy and piped to ffmpeg,
which must be on PATH; without it the script says so and exits 1. Exit codes: 0 written,
1 ffmpeg missing or failed, 2 the target already exists (add --force).
"""

import argparse
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

import numpy as np

WIDTH = 640
HEIGHT = 360
FPS = 15
FRAME_COUNT = 90
"""Six seconds at 15 fps."""
REGION = (400, 120, 600, 300)
"""The region (x0, y0, x1, y1) that the person walks into."""
PERSON_RADIUS = 22
OBJECT_HALF = 8
PERSON_COLOR = (220, 40, 40)
OBJECT_COLOR = (240, 220, 40)
REGION_COLOR = (50, 80, 120)
BACKGROUND_COLOR = (30, 30, 30)
START = (40, 210)
END = (500, 210)
ENCODE_TIMEOUT_SECONDS = 120


def person_center(index: int, count: int) -> tuple[int, int]:
    """Centre (x, y) of the person in frame `index` of `count`: a straight walk START to END."""
    t = index / max(1, count - 1)
    return (round(START[0] + (END[0] - START[0]) * t), round(START[1] + (END[1] - START[1]) * t))


def object_center(index: int, count: int) -> tuple[int, int]:
    """Centre of the carried object: held in front of and above the person."""
    x, y = person_center(index, count)
    return (x + PERSON_RADIUS, y - PERSON_RADIUS // 2)


def render_frame(index: int, count: int) -> np.ndarray:
    """One HEIGHT x WIDTH x 3 uint8 RGB frame."""
    frame = np.empty((HEIGHT, WIDTH, 3), dtype=np.uint8)
    frame[:] = BACKGROUND_COLOR
    x0, y0, x1, y1 = REGION
    frame[y0:y1, x0:x1] = REGION_COLOR
    cx, cy = person_center(index, count)
    ys, xs = np.ogrid[:HEIGHT, :WIDTH]
    frame[(xs - cx) ** 2 + (ys - cy) ** 2 <= PERSON_RADIUS**2] = PERSON_COLOR
    ox, oy = object_center(index, count)
    frame[oy - OBJECT_HALF : oy + OBJECT_HALF + 1, ox - OBJECT_HALF : ox + OBJECT_HALF + 1] = (
        OBJECT_COLOR
    )
    return frame


def main(
    argv: Sequence[str] | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    out: TextIO | None = None,
) -> int:
    """Write the clip and return the exit code."""
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description="Make a short synthetic test video.")
    parser.add_argument("target", type=Path, help="output .mp4 path")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args(argv)
    target: Path = args.target

    ffmpeg = which("ffmpeg")
    if ffmpeg is None:
        out.write(
            "ffmpeg not found on PATH. Install it (Windows: winget install Gyan.FFmpeg) "
            "and open a new terminal.\n"
        )
        return 1
    if target.exists() and not args.force:
        out.write(f"{target} already exists; add --force to overwrite it.\n")
        return 2

    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
        "-i", "-",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target),
    ]  # fmt: skip
    data = b"".join(render_frame(i, FRAME_COUNT).tobytes() for i in range(FRAME_COUNT))
    try:
        result = subprocess.run(
            command, input=data, capture_output=True, timeout=ENCODE_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        out.write(f"ffmpeg could not run: {type(error).__name__}\n")
        return 1
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        out.write(f"ffmpeg failed (exit code {result.returncode}).\n")
        return 1
    out.write(f"wrote {target} ({FRAME_COUNT} frames, {FPS} fps, {WIDTH}x{HEIGHT})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
