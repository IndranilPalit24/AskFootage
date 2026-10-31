"""Zones: round trips with point order, name uniqueness per camera, replace and delete."""

from pathlib import Path

import pytest
from db_library_helpers import CAM_1, CAM_2, NO_SUCH_CAMERA, SQUARE, count_rows, new_camera, zone

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.ports.library_store import DuplicateError, MissingReferenceError

TRIANGLE = ((0.0, 0.0), (1.0, 0.0), (0.5, 1.0))


@pytest.fixture
def zoned(store: SqliteLibraryStore) -> SqliteLibraryStore:
    """Cameras CAM-001 "Front gate" and CAM-002 "Yard", and zone-1 "Gate" on CAM-001."""
    assert store.add_camera(new_camera("Front gate")).id == CAM_1
    assert store.add_camera(new_camera("Yard")).id == CAM_2
    store.add_zone(zone())
    return store


def test_a_zone_round_trips_keeping_point_order(zoned: SqliteLibraryStore) -> None:
    points = ((0.9, 0.1), (0.1, 0.1), (0.0, 1.0), (1, 0), (0.123456789, 0.987654321))
    saved = zone("zone-2", name="Odd shape", points=points)
    zoned.add_zone(saved)

    got = zoned.get_zone("zone-2")

    assert got == saved
    assert got is not None and all(isinstance(value, float) for p in got.points for value in p)


def test_unknown_zone_lookups(zoned: SqliteLibraryStore) -> None:
    assert zoned.get_zone("zone-nope") is None
    assert zoned.list_zones(NO_SUCH_CAMERA) == []
    assert zoned.replace_zone(zone("zone-nope", name="Anything")) is False
    assert zoned.delete_zone("zone-nope") is False


def test_add_zone_refusals(zoned: SqliteLibraryStore) -> None:
    with pytest.raises(DuplicateError, match="id"):
        zoned.add_zone(zone(name="Different name"))
    with pytest.raises(DuplicateError, match="name"):
        zoned.add_zone(zone("zone-2", name="Gate"))
    with pytest.raises(MissingReferenceError):
        zoned.add_zone(zone("zone-3", camera_id=NO_SUCH_CAMERA))
    assert zoned.list_zones() == [zone()]


def test_names_are_unique_per_camera_only(zoned: SqliteLibraryStore) -> None:
    zoned.add_zone(zone("zone-2", camera_id=CAM_2, name="Gate"))
    assert [z.id for z in zoned.list_zones()] == ["zone-1", "zone-2"]


@pytest.mark.parametrize("name", ["gate", "GATE", "gAtE", "Gate"])
def test_names_clash_ignoring_case_on_add(zoned: SqliteLibraryStore, name: str) -> None:
    with pytest.raises(DuplicateError, match="name"):
        zoned.add_zone(zone("zone-2", name=name))
    assert zoned.list_zones() == [zone()]


def test_casefold_is_used_so_non_ascii_case_clashes_too(zoned: SqliteLibraryStore) -> None:
    # str.casefold maps "ß" to "ss"; SQLite's NOCASE (ASCII only) would miss both of these.
    zoned.add_zone(zone("zone-2", name="straße"))
    with pytest.raises(DuplicateError):
        zoned.add_zone(zone("zone-3", name="STRASSE"))
    zoned.add_zone(zone("zone-4", name="ÉCLUSE"))
    with pytest.raises(DuplicateError):
        zoned.add_zone(zone("zone-5", name="écluse"))
    assert [z.name for z in zoned.list_zones(CAM_1)] == ["Gate", "straße", "ÉCLUSE"]


def test_a_name_keeps_the_case_it_was_given(zoned: SqliteLibraryStore) -> None:
    zoned.add_zone(zone("zone-2", name="eXit LANE"))
    stored = zoned.get_zone("zone-2")
    assert stored is not None and stored.name == "eXit LANE"


def test_names_differing_only_in_spacing_do_not_clash(zoned: SqliteLibraryStore) -> None:
    """Only case is ignored; any trimming is the API's to decide."""
    zoned.add_zone(zone("zone-2", name="Gate "))
    assert len(zoned.list_zones(CAM_1)) == 2


def test_a_name_in_any_case_is_fine_on_another_camera(zoned: SqliteLibraryStore) -> None:
    zoned.add_zone(zone("zone-2", camera_id=CAM_2, name="GATE"))
    zoned.add_zone(zone("zone-3", camera_id=CAM_2, name="straße"))
    zoned.add_zone(zone("zone-4", camera_id=CAM_1, name="STRASSE"))
    # Listed in the Protocol's name order, which is SQLite's binary (byte) order.
    assert [(z.camera, z.name) for z in zoned.list_zones()] == [
        (CAM_2, "GATE"),
        (CAM_1, "Gate"),
        (CAM_1, "STRASSE"),
        (CAM_2, "straße"),
    ]


def test_list_zones_orders_by_name_then_id_and_filters(zoned: SqliteLibraryStore) -> None:
    zoned.add_zone(zone("zone-b", camera_id=CAM_2, name="Alley"))
    zoned.add_zone(zone("zone-a", camera_id=CAM_1, name="Alley"))
    zoned.add_zone(zone("zone-c", camera_id=CAM_2, name="Yard"))

    assert [z.id for z in zoned.list_zones()] == ["zone-a", "zone-b", "zone-1", "zone-c"]
    assert [z.id for z in zoned.list_zones(None)] == ["zone-a", "zone-b", "zone-1", "zone-c"]
    assert [z.id for z in zoned.list_zones(CAM_1)] == ["zone-a", "zone-1"]
    assert [z.id for z in zoned.list_zones(CAM_2)] == ["zone-b", "zone-c"]


def test_replace_zone_changes_name_and_points(
    zoned: SqliteLibraryStore, library_path: Path
) -> None:
    assert zoned.replace_zone(zone(name="Main gate", points=TRIANGLE)) is True

    assert zoned.get_zone("zone-1") == zone(name="Main gate", points=TRIANGLE)
    assert count_rows(library_path, "zone_points") == 3  # the old 4 points are gone


def test_replace_zone_may_keep_its_own_name(zoned: SqliteLibraryStore) -> None:
    assert zoned.replace_zone(zone(points=TRIANGLE)) is True
    assert zoned.get_zone("zone-1") == zone(points=TRIANGLE)


def test_replace_zone_never_moves_it_to_another_camera(zoned: SqliteLibraryStore) -> None:
    assert zoned.replace_zone(zone(camera_id=CAM_2, name="Renamed")) is True
    assert zoned.get_zone("zone-1") == zone(camera_id=CAM_1, name="Renamed")


def test_replace_zone_refuses_a_name_taken_on_its_camera_and_changes_nothing(
    zoned: SqliteLibraryStore,
) -> None:
    zoned.add_zone(zone("zone-2", name="Exit lane", points=TRIANGLE))
    zoned.add_zone(zone("zone-3", camera_id=CAM_2, name="Yard"))

    with pytest.raises(DuplicateError):
        zoned.replace_zone(zone("zone-2", name="Gate", points=SQUARE))

    assert zoned.get_zone("zone-2") == zone("zone-2", name="Exit lane", points=TRIANGLE)
    # A name used on another camera is fine.
    assert zoned.replace_zone(zone("zone-2", name="Yard")) is True


@pytest.mark.parametrize("name", ["gate", "GATE", "Gate"])
def test_replace_zone_refuses_another_zones_name_in_any_case_and_changes_nothing(
    zoned: SqliteLibraryStore, name: str
) -> None:
    zoned.add_zone(zone("zone-2", name="Exit lane", points=TRIANGLE))

    with pytest.raises(DuplicateError, match="name"):
        zoned.replace_zone(zone("zone-2", name=name, points=SQUARE))

    assert zoned.get_zone("zone-2") == zone("zone-2", name="Exit lane", points=TRIANGLE)
    assert zoned.get_zone("zone-1") == zone()


def test_replace_zone_refuses_a_non_ascii_case_of_another_zones_name(
    zoned: SqliteLibraryStore,
) -> None:
    zoned.add_zone(zone("zone-2", name="straße"))
    with pytest.raises(DuplicateError):
        zoned.replace_zone(zone("zone-1", name="STRASSE"))
    assert zoned.get_zone("zone-1") == zone()


@pytest.mark.parametrize("name", ["GATE", "gate", "gATE"])
def test_replace_zone_may_rename_to_another_case_of_its_own_name(
    zoned: SqliteLibraryStore, name: str
) -> None:
    zoned.add_zone(zone("zone-2", name="Exit lane"))

    assert zoned.replace_zone(zone(name=name, points=TRIANGLE)) is True

    assert zoned.get_zone("zone-1") == zone(name=name, points=TRIANGLE)
    assert [z.name for z in zoned.list_zones(CAM_1)] == ["Exit lane", name]


def test_replace_zone_may_rename_to_a_non_ascii_case_of_its_own_name(
    zoned: SqliteLibraryStore,
) -> None:
    zoned.add_zone(zone("zone-2", name="straße"))
    assert zoned.replace_zone(zone("zone-2", name="STRASSE")) is True
    stored = zoned.get_zone("zone-2")
    assert stored is not None and stored.name == "STRASSE"


def test_delete_zone_removes_it_and_its_points(
    zoned: SqliteLibraryStore, library_path: Path
) -> None:
    zoned.add_zone(zone("zone-2", name="Other"))

    assert zoned.delete_zone("zone-1") is True
    assert zoned.delete_zone("zone-1") is False

    assert zoned.get_zone("zone-1") is None
    assert [z.id for z in zoned.list_zones()] == ["zone-2"]
    assert count_rows(library_path, "zone_points") == len(SQUARE)  # only zone-2's remain


def test_a_deleted_zones_name_can_be_used_again(zoned: SqliteLibraryStore) -> None:
    zoned.delete_zone("zone-1")
    zoned.add_zone(zone("zone-9", name="Gate"))
    assert zoned.get_zone("zone-9") == zone("zone-9", name="Gate")
