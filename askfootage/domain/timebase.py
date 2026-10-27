"""Frame-number <-> seconds conversion for a constant-frame-rate video.

AskFootage re-encodes every video to a constant frame rate (5 fps by default)
before analysis, so a frame index maps to a time by plain division. This module
is the only place that conversion happens; every other module asks it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_ANALYSIS_FPS = 5.0

# Guards float error: (n / fps) * fps can land just below n, and flooring that
# would return n - 1. Far smaller than any real frame gap, far larger than the error.
_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class Timebase:
    """Maps frame indices to seconds for a constant-frame-rate video."""

    fps: float = DEFAULT_ANALYSIS_FPS

    def __post_init__(self) -> None:
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError(f"fps must be a positive, finite number; got {self.fps!r}")

    def frame_to_seconds(self, frame: int) -> float:
        """Time at which `frame` starts. Frame 0 starts at 0.0 seconds."""
        if frame < 0:
            raise ValueError(f"frame must be >= 0; got {frame}")
        return frame / self.fps

    def seconds_to_frame(self, seconds: float) -> int:
        """Index of the frame on screen at `seconds`."""
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError(f"seconds must be >= 0 and finite; got {seconds!r}")
        return math.floor(seconds * self.fps + _EPSILON)

    def frame_count_for(self, seconds: float) -> int:
        """Smallest number of whole frames that spans at least `seconds`."""
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError(f"seconds must be >= 0 and finite; got {seconds!r}")
        return math.ceil(seconds * self.fps - _EPSILON)

    def duration_seconds(self, frame_count: int) -> float:
        """Length in seconds of `frame_count` consecutive frames."""
        if frame_count < 0:
            raise ValueError(f"frame_count must be >= 0; got {frame_count}")
        return frame_count / self.fps


def format_timecode(seconds: float) -> str:
    """Render seconds as MM:SS.t, truncated to tenths, e.g. 75.25 -> '01:15.2'.

    Truncates rather than rounds, so the label never runs ahead of the frame it
    describes. Minutes keep counting past 59 instead of rolling into hours,
    because footage here is minutes long, not hours.
    """
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"seconds must be >= 0 and finite; got {seconds!r}")
    total_tenths = math.floor(seconds * 10 + _EPSILON)
    minutes, remainder = divmod(total_tenths, 600)
    whole_seconds, tenths = divmod(remainder, 10)
    return f"{minutes:02d}:{whole_seconds:02d}.{tenths}"
