"""PosterRenderer built on ffmpeg: one JPEG, about 640 px wide, from one second of a video.

ffmpeg is found on PATH and started with an argument list (no shell) through a command
runner the app factory supplies (adapters.media.ffmpeg.run_command), with a timeout,
reading only the local file protocol. Failures are OSErrors whose messages quote nothing
ffmpeg printed and name no path.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

POSTER_WIDTH = 640
POSTER_TIMEOUT_SECONDS = 60.0


class _Finished(Protocol):
    returncode: int


class CommandRunner(Protocol):
    """Runs an argument list with a timeout (askfootage.adapters.media.ffmpeg.run_command)."""

    def __call__(self, args: list[str], *, timeout: float) -> _Finished:
        """Run args; raises OSError when it cannot start, TimeoutExpired on timeout."""
        ...


class FfmpegPosterRenderer:
    """Takes one frame of a video with ffmpeg."""

    def __init__(
        self,
        *,
        runner: CommandRunner,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._runner = runner
        self._which = which

    def render(self, video: Path, at_seconds: int, destination: Path) -> None:
        """Write the frame at `at_seconds` to `destination` as a JPEG, 640 px wide."""
        if isinstance(at_seconds, bool) or at_seconds < 0:
            raise ValueError("second must be 0 or more")
        ffmpeg = self._which("ffmpeg")
        if not ffmpeg:
            raise OSError("ffmpeg was not found")
        args = [
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-protocol_whitelist", "file", "-ss", str(at_seconds), "-i", str(video),
            "-frames:v", "1", "-vf", f"scale={POSTER_WIDTH}:-2", "-q:v", "4",
            str(destination),
        ]  # fmt: skip
        try:
            result = self._runner(args, timeout=POSTER_TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError):
            raise OSError("ffmpeg could not be run") from None
        if result.returncode != 0:
            raise OSError(f"ffmpeg failed to make the poster (exit code {result.returncode})")
        if not destination.is_file() or destination.stat().st_size == 0:
            raise OSError("ffmpeg made no poster")
