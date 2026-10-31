"""TrackStore kept in one JSON file per video: <video folder>/tracks.json.

For the command-line tools, which work on a folder of files without the SQLite library.

File format (version 2):

    {"version": 2,
     "meta": {"frame_size": [width, height], "frame_count": 300, "source": "<fingerprint>"},
     "concepts": {"person": {"tracks": [{"track_id": 1, "points": [[frame, x1, y1, x2, y2]]}]}}}

A concept key that is present means the concept was searched for, even when its track list
is empty ("ran, empty"), so an empty result is not paid for again (concept_done). The older
flat form {"person": [track, ...]} is still read; a key there also counts as searched.
frame_size is the pixel size of the prepared video the boxes are measured in.

Safety. Writes of one video are serialised by a per-video lock inside this process; each
write goes to a unique temporary file in the same folder, is flushed and fsynced, then
replaces the old file, so a crash never leaves a half-written file and concurrent writers
never share a temporary name. Several processes writing the same video at once are not
coordinated: the last replace wins. A file that is not valid JSON or does not have this
shape raises TrackDataError (fixed message, no path), which callers working across many
videos catch and skip. Reads never create folders.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint
from askfootage.ports.track_store import TrackDataError
from askfootage.ports.video_store import VideoFileLayout

TRACKS_FILE_NAME = "tracks.json"
FORMAT_VERSION = 2
CORRUPT_MESSAGE = "The stored tracks for that video are unreadable."

__all__ = ["JsonTrackStore", "TrackDataError", "TRACKS_FILE_NAME"]

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _corrupt() -> TrackDataError:
    return TrackDataError(CORRUPT_MESSAGE)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class JsonTrackStore:
    """Implements the TrackStore port over a VideoFileLayout, plus a few extras for the
    command-line tools: concept_done, frame size and prepared-video info."""

    def __init__(self, layout: VideoFileLayout) -> None:
        self._layout = layout

    # --- paths ---------------------------------------------------------------------------

    def _read_path(self, video_id: str) -> Path:
        peek: Callable[[str], Path] | None = getattr(self._layout, "peek_dir", None)
        folder = peek(video_id) if peek is not None else self._layout.video_dir(video_id)
        return folder / TRACKS_FILE_NAME

    def _write_path(self, video_id: str) -> Path:
        return self._layout.video_dir(video_id) / TRACKS_FILE_NAME

    # --- reading -------------------------------------------------------------------------

    def _load(self, path: Path) -> tuple[dict[str, Any], dict[str, list[Any]]]:
        """(meta, concept name -> raw track rows) of the file; empty when it is missing."""
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}, {}
        except (OSError, UnicodeDecodeError):
            raise _corrupt() from None
        try:
            data = json.loads(text)
        except ValueError:
            raise _corrupt() from None
        if not isinstance(data, dict):
            raise _corrupt()
        if "version" not in data:  # the older flat form
            if not all(isinstance(rows, list) for rows in data.values()):
                raise _corrupt()
            return {}, dict(data)
        meta, concepts = data.get("meta", {}), data.get("concepts", {})
        if not isinstance(meta, dict) or not isinstance(concepts, dict):
            raise _corrupt()
        self._check_meta(meta)
        rows: dict[str, list[Any]] = {}
        for name, entry in concepts.items():
            tracks = entry.get("tracks") if isinstance(entry, dict) else None
            if not isinstance(tracks, list):
                raise _corrupt()
            rows[name] = tracks
        return meta, rows

    @staticmethod
    def _check_meta(meta: dict[str, Any]) -> None:
        size = meta.get("frame_size")
        if size is not None and not (
            isinstance(size, list) and len(size) == 2 and all(_is_int(v) and v > 0 for v in size)
        ):
            raise _corrupt()
        count = meta.get("frame_count")
        if count is not None and not (_is_int(count) and count >= 0):
            raise _corrupt()
        source = meta.get("source")
        if source is not None and not isinstance(source, str):
            raise _corrupt()

    @staticmethod
    def _parse(label: str, row: Any) -> Track:
        try:
            points = tuple(
                TrackPoint(int(p[0]), BoundingBox(*map(float, p[1:5]))) for p in row["points"]
            )
            if not _is_int(row["track_id"]) or any(len(p) != 5 for p in row["points"]):
                raise _corrupt()
            return Track(row["track_id"], label, points)
        except TrackDataError:
            raise
        except (KeyError, IndexError, TypeError, ValueError):
            raise _corrupt() from None

    def tracks_for(self, video_id: str, label: str) -> list[Track]:
        """Tracks of this video and label, by track id; empty when none.

        Raises TrackDataError when the video's file is unreadable or malformed.
        """
        _, concepts = self._load(self._read_path(video_id))
        tracks = [self._parse(label, row) for row in concepts.get(label, [])]
        return sorted(tracks, key=lambda t: t.track_id)

    def concept_done(self, video_id: str, concept: str) -> bool:
        """True when the concept was searched for in this video, even if nothing matched."""
        _, concepts = self._load(self._read_path(video_id))
        return concept in concepts

    def frame_size(self, video_id: str) -> tuple[int, int] | None:
        """(width, height) in pixels of the video the boxes are measured in, or None.

        Raises TrackDataError when the video's file is unreadable or malformed.
        """
        meta, _ = self._load(self._read_path(video_id))
        size = meta.get("frame_size")
        return None if size is None else (size[0], size[1])

    def prepared_info(self, video_id: str) -> tuple[int, str] | None:
        """(frame_count, source fingerprint) recorded when the video was prepared, or None."""
        meta, _ = self._load(self._read_path(video_id))
        count, source = meta.get("frame_count"), meta.get("source")
        return None if count is None or source is None else (count, source)

    # --- writing -------------------------------------------------------------------------

    def _mutate(
        self, video_id: str, change: Callable[[dict[str, Any], dict[str, list]], None]
    ) -> None:
        path = self._write_path(video_id)
        with _lock_for(path):
            try:
                meta, concepts = self._load(path)
            except TrackDataError:  # already unreadable: start the file afresh
                meta, concepts = {}, {}
            change(meta, concepts)
            document = {
                "version": FORMAT_VERSION,
                "meta": meta,
                "concepts": {name: {"tracks": rows} for name, rows in concepts.items()},
            }
            self._write_atomically(path, json.dumps(document))

    @staticmethod
    def _write_atomically(path: Path, text: str) -> None:
        descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix="tracks-", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    def save_tracks(self, video_id: str, concept: str, tracks: Sequence[Track]) -> None:
        """Replace the concept's tracks; ValueError for a wrong label or repeated id.

        Saving an empty list records that the concept was searched and found nothing.
        """
        ids = [t.track_id for t in tracks]
        if any(t.label != concept for t in tracks) or len(set(ids)) != len(ids):
            raise ValueError("tracks must carry the concept as label and have unique ids")
        rows = [
            {
                "track_id": t.track_id,
                "points": [[p.frame, p.box.x1, p.box.y1, p.box.x2, p.box.y2] for p in t.points],
            }
            for t in sorted(tracks, key=lambda t: t.track_id)
        ]
        self._mutate(video_id, lambda _meta, concepts: concepts.__setitem__(concept, rows))

    def save_frame_size(self, video_id: str, width: int, height: int) -> None:
        """Record the pixel size of the prepared video; ValueError unless both are positive ints."""
        if not (_is_int(width) and _is_int(height) and width > 0 and height > 0):
            raise ValueError("width and height must be positive whole numbers")
        self._mutate(video_id, lambda meta, _c: meta.__setitem__("frame_size", [width, height]))

    def save_prepared_info(
        self, video_id: str, *, frame_count: int, source_fingerprint: str
    ) -> None:
        """Record the prepared copy's frame count and the fingerprint of the source it
        was made from (used to price later calls and to notice a changed source)."""
        if not (_is_int(frame_count) and frame_count >= 0):
            raise ValueError("frame_count must be a whole number, 0 or more")

        def change(meta: dict[str, Any], _concepts: dict[str, list]) -> None:
            meta["frame_count"] = frame_count
            meta["source"] = source_fingerprint

        self._mutate(video_id, change)

    def delete_video(self, video_id: str) -> int:
        """Remove the video's tracks file; returns how many tracks it held (0 if unreadable)."""
        path = self._read_path(video_id)
        with _lock_for(path):
            try:
                _, concepts = self._load(path)
            except TrackDataError:
                concepts = {}
            path.unlink(missing_ok=True)
        return sum(len(rows) for rows in concepts.values())
