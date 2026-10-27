"""Pure 2-D geometry on bounding boxes and polygons. No I/O, no state."""

from __future__ import annotations

from collections.abc import Sequence

from askfootage.domain.models import BoundingBox, Point


def intersection_area(a: BoundingBox, b: BoundingBox) -> float:
    """Area where two boxes overlap; 0.0 when they only touch or are apart."""
    overlap_width = min(a.x2, b.x2) - max(a.x1, b.x1)
    overlap_height = min(a.y2, b.y2) - max(a.y1, b.y1)
    if overlap_width <= 0 or overlap_height <= 0:
        return 0.0
    return overlap_width * overlap_height


def containment(inner: BoundingBox, outer: BoundingBox) -> float:
    """Fraction of `inner`'s area that lies inside `outer`, from 0.0 to 1.0.

    This is not IoU. A small box held entirely inside a large one scores 1.0,
    where IoU would score near zero. A zero-area `inner` scores 0.0.
    """
    if inner.area == 0:
        return 0.0
    return intersection_area(inner, outer) / inner.area


def relative_offset(anchor: BoundingBox, target: BoundingBox) -> Point:
    """Centre of `target`, expressed in `anchor`'s own frame and scaled by its size.

    Dividing by the anchor's width and height makes the result independent of
    camera distance, so a person walking toward the camera does not look as if
    the object they hold is moving. A zero-size anchor has no frame of
    reference and yields (0.0, 0.0).
    """
    if anchor.width == 0 or anchor.height == 0:
        return (0.0, 0.0)
    anchor_x, anchor_y = anchor.center
    target_x, target_y = target.center
    return ((target_x - anchor_x) / anchor.width, (target_y - anchor_y) / anchor.height)


def point_in_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    """True if `point` lies inside `polygon`, by ray casting.

    Works for concave polygons and for either vertex order. A point exactly on
    an edge may fall on either side.
    """
    if len(polygon) < 3:
        raise ValueError(f"a polygon needs at least 3 vertices; got {len(polygon)}")
    x, y = point
    inside = False
    edges = zip(polygon, [*polygon[1:], polygon[0]], strict=True)
    for (x1, y1), (x2, y2) in edges:
        crosses_row = (y1 > y) != (y2 > y)
        if crosses_row and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside
