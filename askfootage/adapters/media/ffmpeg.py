"""VideoPreparer built on the ffmpeg and ffprobe command-line tools.

The working copy is a constant 5 fps H.264 MP4 with no audio, written as prepared.mp4 in
the destination folder, then measured with ffprobe. The source is read with the demuxer its
extension names and only through the local file protocol.

Both tools are found on PATH and started through a command runner (by default a thin
wrapper over subprocess.run) with an argument list, never a shell command line, and always
with a timeout. Every failure becomes a VideoPreparationError whose message is short and
names no path and quotes nothing ffmpeg printed.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from askfootage.ports.video_store import PreparedVideo, VideoPreparationError

PREPARED_FILE_NAME = "prepared.mp4"
"""File name of the working copy written into the destination folder."""
PREPARED_FPS = 5
"""Frame rate of the working copy."""
MAX_SOURCE_BYTES = 200 * 1024 * 1024
"""Largest source accepted: 200 MiB, the same as the upload limit."""
INPUT_DEMUXERS = {".mp4": "mov", ".mov": "mov", ".mkv": "matroska"}
"""Accepted source extensions (compared in lower case) and the ffmpeg demuxer forced for each.

Forcing the demuxer stops ffmpeg from guessing the format from the content, so a playlist
or concat list saved under a video name cannot make it open other files or URLs.
"""
ALLOWED_SUFFIXES = frozenset(INPUT_DEMUXERS)
"""Source file extensions accepted, compared in lower case."""
ENCODE_TIMEOUT_SECONDS = 900.0
"""Longest an encode may run before it is stopped."""
PROBE_TIMEOUT_SECONDS = 120.0
"""Longest a single ffprobe call may run before it is stopped."""

_INSTALL_HINT = (
    "Install ffmpeg and put it on PATH (on Windows: winget install Gyan.FFmpeg; "
    "on macOS: brew install ffmpeg; on Debian or Ubuntu: apt install ffmpeg)."
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """What a finished command returned."""

    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Runs one command given as an argument list, stopping it after timeout seconds.

    Raises subprocess.TimeoutExpired on timeout and OSError when the command cannot start.
    """

    def __call__(self, args: list[str], *, timeout: float) -> CommandResult:
        """Run args and return its exit code and captured output."""
        ...


def run_command(args: list[str], *, timeout: float) -> CommandResult:
    """The default CommandRunner: subprocess.run with no shell, no stdin and captured output."""
    completed = subprocess.run(
        args,
        shell=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class FfmpegVideoPreparer:
    """Prepares a source video into a 5 fps, silent H.264 MP4 with ffmpeg and ffprobe."""

    def __init__(
        self,
        *,
        runner: CommandRunner = run_command,
        which: Callable[[str], str | None] = shutil.which,
        encode_timeout_seconds: float = ENCODE_TIMEOUT_SECONDS,
        probe_timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
        max_source_bytes: int = MAX_SOURCE_BYTES,
    ) -> None:
        """Set how commands run and are found, the timeouts and the source size limit."""
        self.runner = runner
        self.which = which
        self.encode_timeout_seconds = encode_timeout_seconds
        self.probe_timeout_seconds = probe_timeout_seconds
        self.max_source_bytes = max_source_bytes

    def prepare(self, source: Path, dest_dir: Path) -> PreparedVideo:
        """Write dest_dir/prepared.mp4 from source and describe it.

        Raises VideoPreparationError when the source is missing, of the wrong type, empty
        or too large, when ffmpeg or ffprobe is not installed, or when either one fails or
        times out. On failure no prepared.mp4 is left behind.
        """
        source = self._checked_source(Path(source))
        ffmpeg = self._find("ffmpeg")
        ffprobe = self._find("ffprobe")
        dest_dir = Path(dest_dir).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)
        output = dest_dir / PREPARED_FILE_NAME
        if output.exists() and output.samefile(source):
            raise VideoPreparationError("The source video cannot be its own working copy.")
        try:
            self._encode(ffmpeg, source, output)
            duration, frame_count, size = self._probe(ffprobe, output)
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        return PreparedVideo(
            path=output,
            fps=float(PREPARED_FPS),
            duration_seconds=duration,
            frame_count=frame_count,
            width=None if size is None else size[0],
            height=None if size is None else size[1],
        )

    def _checked_source(self, source: Path) -> Path:
        if not source.exists():
            raise VideoPreparationError("The source video was not found.")
        if not source.is_file():
            raise VideoPreparationError("The source video is not a file.")
        if source.suffix.lower() not in ALLOWED_SUFFIXES:
            raise VideoPreparationError("The source video must be a .mp4, .mov or .mkv file.")
        size = source.stat().st_size
        if size == 0:
            raise VideoPreparationError("The source video is empty.")
        if size > self.max_source_bytes:
            limit_mib = self.max_source_bytes / (1024 * 1024)
            raise VideoPreparationError(f"The source video is too large (limit {limit_mib:g} MiB).")
        return source.resolve()

    def _find(self, tool: str) -> str:
        found = self.which(tool)
        if not found:
            raise VideoPreparationError(f"{tool} was not found. {_INSTALL_HINT}")
        return found

    def _encode(self, ffmpeg: str, source: Path, output: Path) -> None:
        args = [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-protocol_whitelist",
            "file",
            "-f",
            INPUT_DEMUXERS[source.suffix.lower()],
            "-i",
            str(source),
            "-vf",
            f"fps={PREPARED_FPS}",
            "-r",
            str(PREPARED_FPS),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-movflags",
            "+faststart",
            str(output),
        ]
        self._run("ffmpeg", "Video conversion", args, self.encode_timeout_seconds)
        if not output.is_file() or output.stat().st_size == 0:
            raise VideoPreparationError("Video conversion produced no output.")

    def _probe(self, ffprobe: str, output: Path) -> tuple[float, int, tuple[int, int] | None]:
        stream, container = self._probe_json(
            ffprobe,
            [
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=nb_frames,duration,width,height:format=duration",
            ],
            output,
        )
        duration = _non_negative_float(stream.get("duration"))
        if duration is None:
            duration = _non_negative_float(container.get("duration"))
        if duration is None:
            raise VideoPreparationError("Could not read the prepared video's duration.")

        frame_count = _positive_int(stream.get("nb_frames"))
        if frame_count is None:
            counted, _ = self._probe_json(
                ffprobe,
                [
                    "-count_frames",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=nb_read_frames",
                ],
                output,
            )
            frame_count = _positive_int(counted.get("nb_read_frames"))
        if frame_count is None:
            raise VideoPreparationError("The prepared video has no frames.")
        width, height = _positive_int(stream.get("width")), _positive_int(stream.get("height"))
        size = (width, height) if width is not None and height is not None else None
        return duration, frame_count, size

    def _probe_json(
        self, ffprobe: str, query: list[str], output: Path
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        args = [ffprobe, "-v", "error", *query, "-of", "json", str(output)]
        stdout = self._run(
            "ffprobe", "Reading the prepared video", args, self.probe_timeout_seconds
        )
        try:
            parsed = json.loads(stdout)
        except ValueError:
            parsed = None
        streams = parsed.get("streams") if isinstance(parsed, dict) else None
        if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
            raise VideoPreparationError("The prepared video has no readable video stream.")
        container = parsed.get("format") if isinstance(parsed, dict) else None
        return streams[0], container if isinstance(container, dict) else {}

    def _run(self, tool: str, action: str, args: list[str], timeout: float) -> str:
        try:
            result = self.runner(args, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise VideoPreparationError(f"{action} timed out after {timeout:g} seconds.") from None
        except OSError:
            raise VideoPreparationError(f"{tool} could not be started.") from None
        if result.returncode != 0:
            raise VideoPreparationError(f"{action} failed ({tool} exit code {result.returncode}).")
        return result.stdout


def _non_negative_float(value: object) -> float | None:
    try:
        number = float(str(value))
    except ValueError:
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _positive_int(value: object) -> int | None:
    try:
        number = int(str(value))
    except ValueError:
        return None
    return number if number > 0 else None
