"""Use cases for zones: named polygons drawn on a camera's view, in frame fractions."""

from __future__ import annotations

import math
from collections.abc import Sequence

from askfootage.application.errors import InvalidInputError, NotFoundError, ZoneNameTakenError
from askfootage.application.library import (
    CAMERA_NOT_FOUND,
    IdFactory,
    Library,
    new_id,
    require_camera,
    require_camera_filter,
)
from askfootage.ports.library_store import (
    DuplicateError,
    MissingReferenceError,
    Zone,
    ZonePoint,
)

MAX_ZONE_NAME_LENGTH = 60
"""Longest zone name accepted, in characters, before trimming."""
MIN_ZONE_POINTS = 3
MAX_ZONE_POINTS = 50

_NAME_TAKEN = "This camera already has a zone with that name."


def check_zone_name(name: str) -> str:
    """The name trimmed; raises InvalidInputError if it is too long or blank."""
    if len(name) > MAX_ZONE_NAME_LENGTH:
        raise InvalidInputError("name", f"must be at most {MAX_ZONE_NAME_LENGTH} characters")
    trimmed = name.strip()
    if not trimmed:
        raise InvalidInputError("name", "must not be blank")
    return trimmed


def check_zone_points(points: Sequence[Sequence[float]]) -> tuple[ZonePoint, ...]:
    """The points as (x, y) tuples; raises InvalidInputError if any rule is broken.

    A zone has 3 to 50 points; each is exactly [x, y] with finite fractions from 0 to 1.
    """
    if not MIN_ZONE_POINTS <= len(points) <= MAX_ZONE_POINTS:
        raise InvalidInputError(
            "points", f"must have {MIN_ZONE_POINTS} to {MAX_ZONE_POINTS} points"
        )
    checked: list[ZonePoint] = []
    for point in points:
        if len(point) != 2:
            raise InvalidInputError("points", "each point must be exactly [x, y]")
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            raise InvalidInputError("points", "x and y must be numbers from 0 to 1") from None
        if not all(math.isfinite(value) and 0 <= value <= 1 for value in (x, y)):
            raise InvalidInputError("points", "x and y must be numbers from 0 to 1")
        checked.append((x, y))
    return tuple(checked)


def list_zones(library: Library, camera_id: str | None = None) -> list[Zone]:
    """All zones, or only one camera's, ordered by name, then id.

    Raises NotFoundError when camera_id is given and there is no such camera.
    """
    require_camera_filter(library, camera_id)
    zones = library.zones.list_zones(camera_id)
    return sorted(zones, key=lambda zone: (zone.name, zone.id))


def create_zone(
    library: Library,
    camera_id: str,
    name: str,
    points: Sequence[Sequence[float]],
    *,
    make_id: IdFactory = new_id,
) -> Zone:
    """Draw a new zone on a camera's view.

    Raises InvalidInputError for a bad name or points, NotFoundError for an unknown camera
    and ZoneNameTakenError when the camera already has a zone with that name.
    """
    name = check_zone_name(name)
    checked_points = check_zone_points(points)
    require_camera(library, camera_id)
    if _name_taken(library, camera_id, name):
        raise ZoneNameTakenError(_NAME_TAKEN)
    zone = Zone(id=make_id("zone"), camera=camera_id, name=name, points=checked_points)
    try:
        library.zones.add_zone(zone)
    except MissingReferenceError:
        raise NotFoundError(CAMERA_NOT_FOUND) from None
    except DuplicateError:
        if _name_taken(library, camera_id, name):
            raise ZoneNameTakenError(_NAME_TAKEN) from None
        raise
    return zone


def replace_zone(
    library: Library, zone_id: str, name: str, points: Sequence[Sequence[float]]
) -> Zone:
    """Rename or redraw a zone; its camera never changes.

    Raises InvalidInputError for a bad name or points, NotFoundError for an unknown zone
    and ZoneNameTakenError when another zone on the camera already has the new name.
    """
    name = check_zone_name(name)
    checked_points = check_zone_points(points)
    existing = library.zones.get_zone(zone_id)
    if existing is None:
        raise NotFoundError("Zone not found.")
    if _name_taken(library, existing.camera, name, ignore_zone_id=zone_id):
        raise ZoneNameTakenError(_NAME_TAKEN)
    zone = Zone(id=existing.id, camera=existing.camera, name=name, points=checked_points)
    try:
        replaced = library.zones.replace_zone(zone)
    except DuplicateError:
        raise ZoneNameTakenError(_NAME_TAKEN) from None
    if not replaced:
        raise NotFoundError("Zone not found.")
    return zone


def delete_zone(library: Library, zone_id: str) -> None:
    """Delete a zone; raises NotFoundError when there is no such zone."""
    if not library.zones.delete_zone(zone_id):
        raise NotFoundError("Zone not found.")


def _name_taken(
    library: Library, camera_id: str, name: str, *, ignore_zone_id: str | None = None
) -> bool:
    wanted = name.casefold()
    return any(
        zone.name.casefold() == wanted and zone.id != ignore_zone_id
        for zone in library.zones.list_zones(camera_id)
    )
