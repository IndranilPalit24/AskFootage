"""Value types shared by every layer. Pure data: no I/O, no framework imports."""

from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Axis-aligned box in source-frame pixels. The origin is the top-left corner."""

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (self.x1, self.y1, self.x2, self.y2)):
            raise ValueError(f"box coordinates must be finite: {self}")
        if self.x2 < self.x1 or self.y2 < self.y1:
            raise ValueError(f"box corners are inverted: {self}")

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> Point:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def foot(self) -> Point:
        """Bottom-centre: where a standing object meets the ground."""
        return ((self.x1 + self.x2) / 2, self.y2)
