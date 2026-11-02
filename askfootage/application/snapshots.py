"""Where evidence snapshots are kept, and making one for a clip found from tracks.

A snapshot is a JPEG named after its clip id (<directory>/<clip id>.jpg). The clip id is
checked against a strict pattern before it becomes a path, so no request can name a file
outside the directory. A snapshot is made once: an existing one is kept.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from askfootage.application.search_relations import ClipProof
from askfootage.ports.library_store import Clip
from askfootage.ports.snapshots import SnapshotRenderer

logger = logging.getLogger("askfootage.snapshots")
_CLIP_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
SUFFIX = ".jpg"


class SnapshotStore:
    """Evidence snapshots on disk, made by a SnapshotRenderer."""

    def __init__(self, directory: Path, renderer: SnapshotRenderer) -> None:
        self._directory = Path(directory)
        self._renderer = renderer

    def path_for(self, clip_id: str) -> Path:
        """The file a clip's snapshot lives in; ValueError for an id that is not safe."""
        if not isinstance(clip_id, str) or not _CLIP_ID.fullmatch(clip_id):
            raise ValueError("unsafe clip id")
        return self._directory / f"{clip_id}{SUFFIX}"

    def has(self, clip_id: str) -> bool:
        """True when the clip has a snapshot."""
        try:
            return self.path_for(clip_id).is_file()
        except ValueError:
            return False

    def create(self, clip: Clip, proof: ClipProof) -> None:
        """Make the clip's snapshot from its proof, unless it has one or the proof has no plan.

        The image is written to a temporary name and moved into place, so a failed render
        leaves nothing behind. Errors from the renderer propagate.
        """
        plan = proof.snapshot
        if plan is None or self.has(clip.id):
            return
        final = self.path_for(clip.id)
        self._directory.mkdir(parents=True, exist_ok=True)
        partial = final.with_name(f".{clip.id}.partial{SUFFIX}")
        try:
            self._renderer.render(clip.recording_id, plan.frame, plan.boxes, partial)
            os.replace(partial, final)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        logger.info("Snapshot made for clip %s at frame %d", clip.id, plan.frame)
