"""Port for evidence snapshots: one video frame with the matched objects' boxes drawn on it.

askfootage/adapters/media/snapshots.py implements SnapshotRenderer with ffmpeg. Standard
library only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

BoxRole = Literal["object", "person"]


@dataclass(frozen=True, slots=True)
class SnapshotBox:
    """A box to draw, in pixels of the analysed video. The object is red, the person neutral."""

    role: BoxRole
    x1: float
    y1: float
    x2: float
    y2: float


class SnapshotRenderer(Protocol):
    """Draws boxes on one frame of a recording's working copy and saves it as a JPEG."""

    def render(
        self, recording_id: str, frame: int, boxes: Sequence[SnapshotBox], destination: Path
    ) -> None:
        """Write the image to `destination`. Raises OSError (or a subclass) on failure."""
        ...
