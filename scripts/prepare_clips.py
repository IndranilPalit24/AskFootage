r"""Prepare the real clips offline, with no network and no key.

Run it from the project root:

    .venv\Scripts\python.exe -m scripts.prepare_clips
    .venv\Scripts\python.exe -m scripts.prepare_clips videos\clip1.mp4

Each clip becomes a 5 fps H.264 MP4 with the audio removed, written to
<DATA_DIR>/prepared/<clip name>/prepared.mp4 (data/ is git-ignored). For each clip it prints
the frame count and the estimated cost of one SAM request; a request is billed for at least
50 frames, however short the clip.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

if __name__ == "__main__" and not __package__:
    # Run as a file (python scripts\prepare_clips.py), not with -m: make askfootage importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from askfootage.adapters.media.ffmpeg import PREPARED_FPS, FfmpegVideoPreparer  # noqa: E402
from askfootage.adapters.meta.budget import MIN_FRAMES_PER_REQUEST, frames_cost  # noqa: E402
from askfootage.ports.video_store import VideoPreparationError, VideoPreparer  # noqa: E402
from askfootage.settings import ConfigurationError, load_settings  # noqa: E402

DEFAULT_CLIPS = (Path("videos") / "clip1.mp4", Path("videos") / "clip2.mp4")
PREPARED_DIR_NAME = "prepared"
EXIT_OK = 0
EXIT_REFUSED = 2


def prepared_dir(data_dir: Path, source: Path) -> Path:
    """Where a source clip's prepared copy lives: <data_dir>/prepared/<clip name>."""
    return data_dir / PREPARED_DIR_NAME / source.stem


def main(
    argv: Sequence[str] | None = None,
    *,
    data_dir: Path | None = None,
    out: TextIO | None = None,
    preparer: VideoPreparer | None = None,
) -> int:
    """Prepare each clip and print its frame count and estimated cost; returns the exit code."""
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(
        prog="python -m scripts.prepare_clips",
        description="Make the 5 fps, silent H.264 copy of each clip under data/prepared/.",
    )
    parser.add_argument("videos", nargs="*", type=Path, help="default: videos/clip1.mp4 and clip2")
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:  # argparse has already printed the usage message
        return EXIT_OK if stop.code in (0, None) else EXIT_REFUSED
    if data_dir is None:
        try:
            data_dir = load_settings().data_dir
        except ConfigurationError as error:
            out.write(f"REFUSED: {error}\n")
            return EXIT_REFUSED
    preparer = preparer or FfmpegVideoPreparer()
    for source in args.videos or DEFAULT_CLIPS:
        try:
            prepared = preparer.prepare(source, prepared_dir(data_dir, source))
        except VideoPreparationError as error:
            out.write(f"{source.stem}: REFUSED: {error}\n")
            return EXIT_REFUSED
        billed = max(prepared.frame_count, MIN_FRAMES_PER_REQUEST)
        note = "" if billed == prepared.frame_count else f" (billed as {billed}: minimum)"
        out.write(
            f"{source.stem}: {prepared.frame_count} frames at {PREPARED_FPS} fps, "
            f"{prepared.duration_seconds:.2f} s, no audio -> {prepared.path}\n"
        )
        cost = frames_cost(prepared.frame_count)
        out.write(f"{source.stem}: estimated cost per request ${cost}{note}\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
