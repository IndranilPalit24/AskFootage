"""Ports for video files: preparing a working copy and where each video's files live.

askfootage/adapters/media/ffmpeg.py implements VideoPreparer and
askfootage/adapters/storage/local_files.py implements VideoFileLayout. Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class VideoPreparationError(Exception):
    """A video could not be prepared. The message is safe to show and names no server path."""


@dataclass(frozen=True, slots=True)
class PreparedVideo:
    """The constant-frame-rate working copy that analysis runs on."""

    path: Path
    fps: float
    duration_seconds: float
    frame_count: int
    width: int | None = None
    height: int | None = None
    """Pixel size of the frames, when the preparer could read it (the unit of box coordinates)."""

    def __post_init__(self) -> None:
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        if self.duration_seconds < 0 or self.frame_count < 0:
            raise ValueError("duration_seconds and frame_count must not be negative")
        if (self.width is None) != (self.height is None) or any(
            v is not None and v <= 0 for v in (self.width, self.height)
        ):
            raise ValueError("width and height must be given together and be positive")


class VideoPreparer(Protocol):
    """Turns a source video into the working copy (see PreparedVideo)."""

    def prepare(self, source: Path, dest_dir: Path) -> PreparedVideo:
        """Write the working copy into dest_dir and describe it.

        Raises VideoPreparationError when the source is missing, of the wrong type, too
        large, or the conversion fails.
        """
        ...


class VideoFileLayout(Protocol):
    """Where one video's files live on disk. video_id is the recording id."""

    def video_dir(self, video_id: str) -> Path:
        """The folder for this video (created if missing). Rejects ids that could escape it."""
        ...

    def raw_dir(self, video_id: str) -> Path:
        """The folder for the original upload (created if missing)."""
        ...

    def prepared_path(self, video_id: str) -> Path:
        """Where the prepared working copy goes."""
        ...
