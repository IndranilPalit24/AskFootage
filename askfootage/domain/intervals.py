"""Frame intervals where a relation held, with the evidence for why.

The relation rules (relations.py) return these; the index flow turns them into clips and
the "Why this matched" panel shows their evidence. Frames are inclusive at both ends.
Convert to seconds only at the edge, with a Timebase. Pure data: no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from askfootage.domain.timebase import Timebase

RelationKind = Literal["carrying", "in_zone", "dwell"]
"""carrying: an object moved with a person; in_zone: a track entered a region; dwell: a
track stayed inside a region. The same words the library uses for clip evidence."""

RELATION_KINDS: tuple[RelationKind, ...] = ("carrying", "in_zone", "dwell")


@dataclass(frozen=True, slots=True)
class IntervalEvidence:
    """Why an interval matched: the rule, the tracks involved and the numbers it measured.

    track_ids lists the tracks the rule used, e.g. (person, box) for carrying.
    measures holds named, finite numbers in a fixed order, e.g. (("frames_inside", 42.0),).
    """

    kind: RelationKind
    track_ids: tuple[int, ...]
    measures: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in RELATION_KINDS:
            raise ValueError(f"kind must be one of {', '.join(RELATION_KINDS)}")
        if not self.track_ids:
            raise ValueError("track_ids must name at least one track")
        for name, value in self.measures:
            if not name or not math.isfinite(value):
                raise ValueError("each measure needs a name and a finite value")


@dataclass(frozen=True, slots=True)
class Interval:
    """Frames start_frame..end_frame (both inclusive) where a relation held."""

    start_frame: int
    end_frame: int
    evidence: IntervalEvidence

    def __post_init__(self) -> None:
        if self.start_frame < 0:
            raise ValueError(f"start_frame must be >= 0; got {self.start_frame}")
        if self.end_frame < self.start_frame:
            raise ValueError("end_frame must not be before start_frame")

    @property
    def frame_count(self) -> int:
        """Number of frames covered, counting both ends."""
        return self.end_frame - self.start_frame + 1

    def seconds(self, timebase: Timebase) -> tuple[float, float]:
        """(start, end) in seconds: from the start of the first frame to the end of the last."""
        return (
            timebase.frame_to_seconds(self.start_frame),
            timebase.frame_to_seconds(self.end_frame) + timebase.duration_seconds(1),
        )
