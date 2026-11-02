"""Poster frames: one JPEG still of a recording, cached on disk.

A poster is named <recording id>-<second>.jpg inside one directory. The recording id is
checked against a strict pattern and the second is a whole number, so no request can name a
file outside the directory. A poster is made once: an existing one is served again.
Making one only reads the footage file; it calls no model and spends nothing.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path
from typing import Protocol

from askfootage.application.errors import NotFoundError
from askfootage.application.library import Library
from askfootage.application.recordings import FootageSource, find_footage

logger = logging.getLogger("askfootage.posters")
_RECORDING_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
SUFFIX = ".jpg"
MAX_SECOND = 86_400
"""Largest second a request may ask for (a day); longer asks are refused by the route."""
_NOT_AVAILABLE = "Poster not available."


class PosterRenderer(Protocol):
    """Writes one JPEG still of a video."""

    def render(self, video: Path, at_seconds: int, destination: Path) -> None:
        """Write the frame at `at_seconds` of `video` to `destination`; OSError on failure."""
        ...


class PosterStore:
    """Poster frames on disk, made by a PosterRenderer."""

    def __init__(self, directory: Path, renderer: PosterRenderer) -> None:
        self._directory = Path(directory)
        self._renderer = renderer

    def path_for(self, recording_id: str, at_seconds: int) -> Path:
        """The cache file for a poster; ValueError when the id or second is not safe."""
        if not isinstance(recording_id, str) or not _RECORDING_ID.fullmatch(recording_id):
            raise ValueError("unsafe recording id")
        if isinstance(at_seconds, bool) or not isinstance(at_seconds, int):
            raise ValueError("second must be a whole number")
        if not 0 <= at_seconds <= MAX_SECOND:
            raise ValueError("second out of range")
        path = self._directory / f"{recording_id}-{at_seconds}{SUFFIX}"
        if path.resolve().parent != self._directory.resolve():
            raise ValueError("poster path escapes its directory")
        return path

    def ensure(self, recording_id: str, video: Path, at_seconds: int) -> Path:
        """The poster file, made first when missing. Renderer errors propagate."""
        final = self.path_for(recording_id, at_seconds)
        if final.is_file():
            return final
        self._directory.mkdir(parents=True, exist_ok=True)
        partial = final.with_name(f".{uuid.uuid4().hex}.partial{SUFFIX}")
        try:
            self._renderer.render(video, at_seconds, partial)
            os.replace(partial, final)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        logger.info("Poster made for recording %s at %d s", recording_id, at_seconds)
        return final


def has_footage(library: Library, footage: FootageSource, recording_id: str) -> bool:
    """True when the recording is known, is meant to have footage, and a file is attached."""
    recording = library.recordings.get_recording(recording_id)
    return (
        recording is not None
        and recording.has_footage
        and footage.footage_for(recording) is not None
    )


def get_poster(
    library: Library,
    footage: FootageSource,
    posters: PosterStore | None,
    recording_id: str,
    at_seconds: float | None,
) -> Path:
    """The poster JPEG of a recording at a second (default: the middle of the recording).

    The second is rounded down and kept inside the recording. Raises NotFoundError when the
    recording is unknown, has no footage, or the frame cannot be made (no poster store,
    ffmpeg missing or failing); the message never says why.
    """
    video = find_footage(library, footage, recording_id)
    recording = library.recordings.get_recording(recording_id)
    length = recording.length_seconds if recording is not None else 0
    second = length // 2 if at_seconds is None else int(at_seconds)
    if length > 0:
        second = min(second, length - 1)
    second = max(0, second)
    if posters is None:
        raise NotFoundError(_NOT_AVAILABLE)
    try:
        return posters.ensure(recording_id, video, second)
    except (OSError, ValueError):
        logger.warning("Poster for recording %s could not be made", recording_id)
        raise NotFoundError(_NOT_AVAILABLE) from None
