r"""Ingest both real clips into SQLite, offline, from the saved SAM replies.

Run it from the project root, after scripts.record_sam_demo (or with the demo/sam folder
from the repository):

    .venv\Scripts\python.exe -m scripts.ingest_real_clips

For each clip it runs application/ingest_video.py with SamPerception over a ReplayTransport,
so every reply comes from demo/sam and nothing is sent to Meta: no key, no network, no
spend. The prepared video (data/prepared/<clip>/prepared.mp4, the very file that was
uploaded) is copied, not re-encoded, so the upload's fingerprint still matches its
recording. Tracks of "person", "cardboard box" (asked for as "box") and "hand" are stitched
and stored in <data-dir>/library.sqlite, next to a camera and a ready recording per clip,
so the API can search them. It prints a table of tracks per clip and noun. It reads no
settings and no environment.

Exit codes: 0 done, 2 refused.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from math import ceil
from pathlib import Path
from typing import TextIO

if __name__ == "__main__" and not __package__:
    # Run as a file (python scripts\ingest_real_clips.py), not with -m: make askfootage importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from askfootage.adapters.media.ffmpeg import PreparedCopyPreparer  # noqa: E402
from askfootage.adapters.meta.record_replay import ReplayTransport  # noqa: E402
from askfootage.adapters.meta.sam import DEFAULT_PROMPTS, SamPerception  # noqa: E402
from askfootage.adapters.meta.transport import Transport  # noqa: E402
from askfootage.adapters.sqlite.store import SqliteLibraryStore  # noqa: E402
from askfootage.adapters.sqlite.tracks import SqliteTrackStore  # noqa: E402
from askfootage.adapters.storage.local_files import LocalVideoFiles  # noqa: E402
from askfootage.application.errors import ApplicationError  # noqa: E402
from askfootage.application.ingest_video import IngestServices, ingest_video  # noqa: E402
from askfootage.domain.timebase import Timebase  # noqa: E402
from askfootage.domain.tracks import Track  # noqa: E402
from askfootage.ports.library_store import (  # noqa: E402
    LibraryError,
    NewCamera,
    Recording,
)
from askfootage.ports.perception import Perception  # noqa: E402
from askfootage.ports.video_store import VideoPreparationError  # noqa: E402

EXIT_OK = 0
EXIT_REFUSED = 2
CLIPS = ("clip1", "clip2")
NOUNS = ("person", "cardboard box", "hand")
"""The nouns asked of every clip. "cardboard box" is sent to SAM as "box" (DEFAULT_PROMPTS)."""
LIBRARY_NAME = "library.sqlite"
DEFAULT_DATA_DIR = Path("data") / "real"
DEFAULT_PREPARED_DIR = Path("data") / "prepared"
DEFAULT_RECORDINGS_DIR = Path("demo") / "sam"
DEFAULT_DAY = date(2026, 10, 30)
"""The demo dataset's "today", so the UI's default day shows the clips."""
CAMERA_ID = "CAM-001"
CAMERA_NAME = "Real clips (replayed)"
START_TIMES = {"clip1": time(9, 0), "clip2": time(9, 30)}
COLUMNS = ("clip", "noun", "raw", "stored", "ids", "frames", "seconds")


class _Observing:
    """Perception wrapper that remembers how many tracks SAM gave before stitching."""

    def __init__(self, inner: Perception) -> None:
        self._inner = inner
        self.raw: dict[tuple[str, str], int] = {}

    def detect_and_track(self, video_path: Path, noun: str) -> list[Track]:
        tracks = self._inner.detect_and_track(video_path, noun)
        self.raw[(video_path.parent.name, noun)] = len(tracks)
        return tracks


def _ensure_camera(store: SqliteLibraryStore) -> None:
    if store.get_camera(CAMERA_ID) is None:
        store.add_camera(
            NewCamera(
                name=CAMERA_NAME,
                ip="192.0.2.10",
                username="replay",
                status="online",
                location=None,
                department=None,
                created_at=datetime(2026, 10, 30, 8, 0, tzinfo=UTC),
            )
        )


def _ensure_recording(store: SqliteLibraryStore, clip: str, day: date, seconds: int) -> None:
    if store.get_recording(clip) is None:
        store.add_recording(Recording(clip, CAMERA_ID, day, START_TIMES[clip], seconds, "waiting"))


def _row(
    clip: str, noun: str, raw: int | None, tracks: Sequence[Track], timebase: Timebase
) -> list[str]:
    if not tracks:
        return [clip, noun, _count(raw), "0", "-", "-", "-"]
    first = min(t.first_frame for t in tracks)
    last = max(t.last_frame for t in tracks)
    start, end = timebase.frame_to_seconds(first), timebase.frame_to_seconds(last)
    return [
        clip,
        noun,
        _count(raw),
        str(len(tracks)),
        ",".join(str(t.track_id) for t in tracks),
        f"{first}-{last}",
        f"{start:.1f}-{end:.1f}",
    ]


def _count(raw: int | None) -> str:
    return "-" if raw is None else str(raw)


def _table(rows: Sequence[Sequence[str]]) -> str:
    everything = [COLUMNS, *rows]
    widths = [max(len(row[i]) for row in everything) for i in range(len(COLUMNS))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in everything
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: Transport | None = None,
    preparer: PreparedCopyPreparer | None = None,
    out: TextIO | None = None,
) -> int:
    """Ingest both clips from saved replies; returns the exit code."""
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(
        prog="python -m scripts.ingest_real_clips",
        description="Ingest the two real clips from the saved SAM replies (offline).",
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--prepared-dir", type=Path, default=DEFAULT_PREPARED_DIR)
    parser.add_argument("--recordings-dir", type=Path, default=DEFAULT_RECORDINGS_DIR)
    parser.add_argument("--day", type=date.fromisoformat, default=DEFAULT_DAY)
    parser.add_argument("--force", action="store_true", help="redo nouns already stored")
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:  # argparse has already printed the usage message
        return EXIT_OK if stop.code in (0, None) else EXIT_REFUSED

    sources = {clip: args.prepared_dir / clip / "prepared.mp4" for clip in CLIPS}
    for clip, source in sources.items():
        if not source.is_file():
            out.write(f"REFUSED: the prepared video of {clip} was not found.\n")
            return EXIT_REFUSED

    preparer = preparer or PreparedCopyPreparer()
    replay: Transport = transport if transport is not None else ReplayTransport(args.recordings_dir)
    observing = _Observing(SamPerception(replay, prompts=DEFAULT_PROMPTS))
    try:
        store = SqliteLibraryStore(args.data_dir / LIBRARY_NAME)
        tracks = SqliteTrackStore(store)
        services = IngestServices(
            perception=observing,
            preparer=preparer,
            layout=LocalVideoFiles(args.data_dir),
            tracks=tracks,
        )
        _ensure_camera(store)
        rows: list[list[str]] = []
        timebase = Timebase()
        for clip, source in sources.items():
            seconds = ceil(preparer.describe(source).duration_seconds)
            _ensure_recording(store, clip, args.day, seconds)
            ingest_video(services, clip, source, NOUNS, force=args.force)
            store.set_recording_status(clip, "ready")
            rows.extend(
                _row(
                    clip,
                    noun,
                    observing.raw.get((clip, noun)),
                    tracks.tracks_for(clip, noun),
                    timebase,
                )
                for noun in NOUNS
            )
    except (ApplicationError, LibraryError, VideoPreparationError, OSError) as error:
        message = getattr(error, "message", None) or type(error).__name__
        out.write(f"REFUSED: {message}\n")
        return EXIT_REFUSED

    out.write(_table(rows) + "\n")
    out.write("raw = tracks SAM returned; stored = tracks kept after stitching broken ids\n")
    out.write(f"library: {args.data_dir / LIBRARY_NAME}\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
