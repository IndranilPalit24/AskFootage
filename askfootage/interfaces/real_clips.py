r"""The API over the two real clips ingested by scripts.ingest_real_clips.

    .venv\Scripts\python.exe -m uvicorn askfootage.interfaces.real_clips:create_app `
        --factory --port 8000

It serves data/real/library.sqlite (cameras, recordings and the stored tracks), plays
videos/<recording id>.mp4, and makes evidence snapshots from each recording's working copy
(data/real/<recording id>/prepared.mp4) into data/real/snapshots. Nothing here calls Meta,
and no setting or key is read: the folders are worked out from this file's place in the
repository. Run scripts.ingest_real_clips first; without it the library is empty.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI

from askfootage.adapters.media.snapshots import FfmpegSnapshotRenderer
from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.adapters.sqlite.tracks import SqliteTrackStore
from askfootage.application.library import Library
from askfootage.application.snapshots import SnapshotStore
from askfootage.interfaces.api.app import REPO_ROOT
from askfootage.interfaces.api.app import create_app as create_demo_app
from askfootage.interfaces.api.context import ApiContext
from askfootage.ports.library_store import Recording

DEFAULT_DATA_DIR = REPO_ROOT / "data" / "real"
DEFAULT_VIDEOS_DIR = REPO_ROOT / "videos"
SNAPSHOTS_DIR_NAME = "snapshots"


class PerRecordingFootage:
    """Each recording plays <videos_dir>/<recording id>.mp4 when that file exists."""

    def __init__(self, videos_dir: Path) -> None:
        self._dir = Path(videos_dir)

    def footage_for(self, recording: Recording) -> Path | None:
        """The recording's own video, or None when it is not there."""
        path = self._dir / f"{recording.id}.mp4"
        return path if path.is_file() else None


def create_app(data_dir: Path = DEFAULT_DATA_DIR, videos_dir: Path = DEFAULT_VIDEOS_DIR) -> FastAPI:
    """The API over the ingested real clips (an empty library if nothing was ingested)."""
    library = SqliteLibraryStore(Path(data_dir) / "library.sqlite")
    tracks = SqliteTrackStore(library)
    prepared = Path(data_dir)
    renderer = FfmpegSnapshotRenderer(lambda recording_id: prepared / recording_id / "prepared.mp4")
    app = create_demo_app(
        library=Library.from_store(library),
        tracks=tracks,
        snapshots=SnapshotStore(prepared / SNAPSHOTS_DIR_NAME, renderer),
        videos_dir=videos_dir,
    )
    app.state.context = _with_footage(app.state.context, PerRecordingFootage(videos_dir))
    return app


def _with_footage(context: ApiContext, footage: PerRecordingFootage) -> ApiContext:
    return replace(context, footage=footage)
