"""Object tracks: where one tracked object's box was, frame by frame.

A track is what perception returns for one object it followed through a video. Frames are
indices into the prepared, constant-frame-rate video (see timebase.py); a track may skip
frames where the object was hidden or not detected. Pure data: no I/O.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from askfootage.domain.models import BoundingBox

LABEL_MAX = 40
"""Longest label, the same limit as an object noun."""


@dataclass(frozen=True, slots=True)
class TrackPoint:
    """The object's box on one frame."""

    frame: int
    box: BoundingBox

    def __post_init__(self) -> None:
        if isinstance(self.frame, bool) or not isinstance(self.frame, int):
            raise TypeError(f"frame must be an int; got {self.frame!r}")
        if self.frame < 0:
            raise ValueError(f"frame must be >= 0; got {self.frame}")
        if not isinstance(self.box, BoundingBox):
            raise TypeError("box must be a BoundingBox")


@dataclass(frozen=True, slots=True)
class Track:
    """One object followed through a video.

    track_id is unique within one video and label. label is the neutral object noun the
    track was found for, such as "person" or "cardboard box"; never an identity.
    points is non-empty and ordered by strictly increasing frame (no frame twice).
    """

    track_id: int
    label: str
    points: tuple[TrackPoint, ...]
    _frames: tuple[int, ...] = field(init=False, repr=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        if isinstance(self.track_id, bool) or not isinstance(self.track_id, int):
            raise TypeError(f"track_id must be an int; got {self.track_id!r}")
        if self.track_id < 0:
            raise ValueError(f"track_id must be >= 0; got {self.track_id}")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("label must be a non-blank string")
        if self.label != self.label.strip() or len(self.label) > LABEL_MAX:
            raise ValueError(f"label must be trimmed and at most {LABEL_MAX} characters")
        if not isinstance(self.points, tuple) or not self.points:
            raise ValueError("points must be a non-empty tuple")
        frames = tuple(point.frame for point in self.points)
        if any(later <= earlier for earlier, later in zip(frames, frames[1:], strict=False)):
            raise ValueError("points must be in strictly increasing frame order")
        object.__setattr__(self, "_frames", frames)

    @property
    def first_frame(self) -> int:
        """Frame of the first point."""
        return self._frames[0]

    @property
    def last_frame(self) -> int:
        """Frame of the last point."""
        return self._frames[-1]

    @property
    def frames(self) -> tuple[int, ...]:
        """Every frame that has a point, in increasing order."""
        return self._frames

    def has_frame(self, frame: int) -> bool:
        """True when the track has a point on this exact frame."""
        return self.box_at(frame) is not None

    def box_at(self, frame: int) -> BoundingBox | None:
        """The box on this exact frame, or None when the track has no point there."""
        index = bisect.bisect_left(self._frames, frame)
        if index < len(self._frames) and self._frames[index] == frame:
            return self.points[index].box
        return None
