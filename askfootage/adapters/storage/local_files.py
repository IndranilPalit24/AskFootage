"""Where each video's files live on the local disk.

Layout, under a data folder passed in by the caller:

    <data_dir>/<video_id>/raw/          the original upload
    <data_dir>/<video_id>/prepared.mp4  the prepared working copy

A video id is used as a folder name, so it is checked twice before any path is built or
any folder is created: it must be 1 to 64 characters of A-Z, a-z, 0-9, "_" and "-" (which
rules out "..", slashes, backslashes, drive letters, absolute paths and the empty id) and
must not be a reserved Windows device name; and the resolved folder must sit directly
inside the resolved data folder, which also catches a folder that is a link to elsewhere.
"""

from __future__ import annotations

import re
from pathlib import Path

PREPARED_FILE_NAME = "prepared.mp4"
"""File name of the prepared working copy inside a video's folder."""
RAW_DIR_NAME = "raw"
"""Folder name, inside a video's folder, for the original upload."""

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)


class InvalidVideoIdError(ValueError):
    """A video id that is not safe to use as a folder name. The message names no path."""


class LocalVideoFiles:
    """VideoFileLayout on the local disk, rooted at a data folder given by the caller."""

    def __init__(self, data_dir: Path) -> None:
        """Anchor the layout at data_dir, made absolute now so later cwd changes do not move it."""
        self._root = Path(data_dir).resolve()

    def video_dir(self, video_id: str) -> Path:
        """The folder for this video, created if missing. Raises InvalidVideoIdError."""
        folder = self._safe_video_dir(video_id)
        folder.mkdir(parents=True, exist_ok=True)
        self._check_inside_root(folder)
        return folder

    def raw_dir(self, video_id: str) -> Path:
        """The folder for the original upload, created if missing. Raises InvalidVideoIdError."""
        raw = self.video_dir(video_id) / RAW_DIR_NAME
        raw.mkdir(exist_ok=True)
        return raw

    def prepared_path(self, video_id: str) -> Path:
        """Where the prepared working copy goes; its folder exists. Raises InvalidVideoIdError."""
        return self.video_dir(video_id) / PREPARED_FILE_NAME

    def _safe_video_dir(self, video_id: str) -> Path:
        if not isinstance(video_id, str) or _VIDEO_ID.fullmatch(video_id) is None:
            raise InvalidVideoIdError("Invalid video id: use 1 to 64 letters, digits, '_' or '-'.")
        if video_id.lower() in _WINDOWS_DEVICE_NAMES:
            raise InvalidVideoIdError("Invalid video id: that name is reserved by the system.")
        folder = self._root / video_id
        self._check_inside_root(folder)
        return folder

    def _check_inside_root(self, folder: Path) -> None:
        if folder.resolve().parent != self._root:
            raise InvalidVideoIdError("Invalid video id: it points outside the data folder.")
