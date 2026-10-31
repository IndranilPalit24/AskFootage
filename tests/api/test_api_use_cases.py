"""The application layer on its own: interpreter, day filling, validation and store refusals.

No HTTP here: the use cases are called directly with in-memory stores.
"""

from __future__ import annotations

import ast
from dataclasses import fields, replace
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest
from api_fakes import REPO_ROOT, InMemoryLibrary

from askfootage.application import recordings, saved_clips, search, zones
from askfootage.application.errors import (
    AlreadySavedError,
    InvalidInputError,
    NotFoundError,
    ZoneNameTakenError,
)
from askfootage.application.library import Library, new_id
from askfootage.application.search import QuestionInterpreter, SearchPlan
from askfootage.ports.library_store import (
    DuplicateError,
    MissingReferenceError,
    Recording,
    Zone,
)

THURSDAY = date(2026, 10, 29)
TODAY = date(2026, 10, 30)
ZONE_NAMES = ["Exit lane", "Loading door"]
TRIANGLE = [(0.1, 0.1), (0.9, 0.1), (0.5, 0.9)]


@pytest.fixture
def library(store: InMemoryLibrary) -> Library:
    """The use cases' view of the seeded in-memory store."""
    return Library.from_store(store)


# --- QuestionInterpreter --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "kinds", "zone_names", "understood"),
    [
        ("someone carrying a box", {"carrying"}, set(), True),
        ("Parcels?", {"carrying"}, set(), True),
        ("who stood around", {"dwell"}, set(), True),
        ("LOITERING", {"dwell"}, set(), True),
        ("at the loading door", set(), {"Loading door"}, True),
        ("loading-door", set(), {"Loading door"}, True),
        ("Exit  lane", set(), {"Exit lane"}, True),
        ("waiting with a package in the exit lane", {"carrying", "dwell"}, {"Exit lane"}, True),
        ("anyone", set(), set(), True),
        ("people", set(), set(), True),
        ("red bicycle", set(), set(), False),
        ("loading", set(), set(), False),
        ("boxer shorts", set(), set(), False),
        ("", set(), set(), False),
    ],
)
def test_the_interpreter_turns_words_into_conditions(
    question: str, kinds: set[str], zone_names: set[str], understood: bool
) -> None:
    plan = QuestionInterpreter().interpret(question, ZONE_NAMES)
    assert plan == SearchPlan(
        evidence_kinds=frozenset(kinds),  # type: ignore[arg-type]
        zone_names=frozenset(zone_names),
        understood=understood,
    )


def test_the_interpreter_only_knows_the_cameras_own_zones() -> None:
    assert QuestionInterpreter().interpret("loading door", []).understood is False


def test_a_plan_matches_only_clips_meeting_every_condition(store: InMemoryLibrary) -> None:
    door_carry = store.clips["clip-1029-061405"]  # carrying + in_zone, Loading door
    lane_dwell = store.clips["clip-1029-072140"]  # dwell + in_zone, Exit lane
    no_zone = store.clips["clip-1029-091522"]  # carrying, no zone
    plan = SearchPlan(
        evidence_kinds=frozenset({"carrying"}), zone_names=frozenset({"loading DOOR"})
    )
    assert [plan.matches(c) for c in (door_carry, lane_dwell, no_zone)] == [True, False, False]
    assert all(SearchPlan().matches(c) for c in (door_carry, lane_dwell, no_zone))
    assert not any(SearchPlan(understood=False).matches(c) for c in (door_carry, no_zone))


def test_search_uses_whatever_interpreter_it_is_given(library: Library) -> None:
    class OnlyExitLane:
        def interpret(self, question: str, zone_names: object) -> SearchPlan:
            return SearchPlan(zone_names=frozenset({"Exit lane"}))

    result = search.search_day(library, OnlyExitLane(), "anything", THURSDAY, "CAM-001")
    assert [found.clip.id for found in result.clips] == ["clip-1029-072140", "clip-1029-131430"]
    assert {found.camera for found in result.clips} == {"CAM-001"}


def test_search_checks_the_question_and_camera(library: Library) -> None:
    interpreter = QuestionInterpreter()
    with pytest.raises(InvalidInputError, match="question: must not be blank"):
        search.search_day(library, interpreter, " \t", THURSDAY, "CAM-001")
    with pytest.raises(InvalidInputError, match="at most 300"):
        search.search_day(library, interpreter, "x" * 301, THURSDAY, "CAM-001")
    with pytest.raises(NotFoundError):
        search.search_day(library, interpreter, "people", THURSDAY, "garage")


def test_check_question_trims_and_counts_before_trimming() -> None:
    assert search.check_question("  people  ") == "people"
    assert search.check_question("x" * 300) == "x" * 300
    with pytest.raises(InvalidInputError):
        search.check_question(" " * 301)


def test_the_not_understood_note_lists_no_zones_when_the_camera_has_none(
    store: InMemoryLibrary, library: Library
) -> None:
    store.zones.clear()
    result = search.search_day(
        library, QuestionInterpreter(), "bicycle", date(2026, 10, 28), "CAM-001"
    )
    assert result.clips == []
    assert result.note is not None and "zone" not in result.note


# --- Days -------------------------------------------------------------------------------------


def test_days_are_seven_oldest_first_ending_today_with_zeros(library: Library) -> None:
    days = recordings.list_days(library, "CAM-001", TODAY)
    assert [d.day for d in days] == [TODAY - timedelta(days=n) for n in range(6, -1, -1)]
    assert [(d.recordings, d.ready) for d in days] == [
        (1, 1),
        (0, 0),
        (2, 2),
        (2, 2),
        (3, 3),
        (6, 5),
        (4, 2),
    ]


def test_days_cross_a_month_boundary_and_can_be_all_zero(library: Library) -> None:
    days = recordings.list_days(library, "CAM-001", date(2026, 3, 2))
    assert [d.day for d in days][:2] == [date(2026, 2, 24), date(2026, 2, 25)]
    assert all((d.recordings, d.ready) == (0, 0) for d in days)


def test_days_for_an_unknown_camera_raise_not_found(library: Library) -> None:
    with pytest.raises(NotFoundError, match="Camera not found."):
        recordings.list_days(library, "garage", TODAY)


# --- Status, recordings, footage and clips -------------------------------------------------------


def test_status_is_always_demo_mode() -> None:
    assert recordings.get_status().demo_mode is True


def test_status_holds_only_demo_mode_and_needs_no_camera() -> None:
    # Contract 1.1.0 dropped the camera from Status: it no longer depends on the store.
    assert [field.name for field in fields(recordings.get_status())] == ["demo_mode"]


def test_registering_an_upload_makes_a_waiting_recording(
    store: InMemoryLibrary, library: Library
) -> None:
    recording = recordings.register_upload(
        library, "CAM-001", TODAY, make_id=lambda prefix: f"{prefix}-new"
    )
    assert recording == Recording(
        id="rec-new",
        camera="CAM-001",
        day=TODAY,
        start_time=time(0, 0, 0),
        length_seconds=0,
        status="waiting",
    )
    assert store.recordings["rec-new"] == recording
    with pytest.raises(NotFoundError):
        recordings.register_upload(library, "garage", TODAY)


def test_a_camera_removed_mid_upload_is_not_found(
    store: InMemoryLibrary, library: Library, monkeypatch: pytest.MonkeyPatch
) -> None:
    def vanished(recording: Recording) -> None:
        raise MissingReferenceError("gone")

    monkeypatch.setattr(store, "add_recording", vanished)
    with pytest.raises(NotFoundError, match="Camera not found."):
        recordings.register_upload(library, "CAM-001", TODAY)


def test_footage_is_found_only_for_known_recordings_with_a_file(
    library: Library, tmp_path: Path
) -> None:
    video = tmp_path / "clip1.mp4"

    class OneFile:
        def footage_for(self, recording: Recording) -> Path | None:
            return video if video.exists() else None

    with pytest.raises(NotFoundError, match="Recording not found."):
        recordings.find_footage(library, OneFile(), "rec-nope")
    with pytest.raises(NotFoundError, match="Footage file not attached."):
        recordings.find_footage(library, OneFile(), "rec-1029-0600")
    video.write_bytes(b"x")
    assert recordings.find_footage(library, OneFile(), "rec-1029-0600") == video


def test_recordings_are_sorted_even_if_a_store_is_not(library: Library) -> None:
    found = recordings.list_recordings(library, "CAM-001", THURSDAY)
    assert [r.start_time for r in found] == sorted(r.start_time for r in found)
    with pytest.raises(NotFoundError):
        recordings.list_recordings(library, "garage", THURSDAY)


def test_get_clip(library: Library) -> None:
    found = recordings.get_clip(library, "clip-1029-104215")
    assert (found.clip.zone, found.camera) == ("Loading door", "CAM-001")
    with pytest.raises(NotFoundError, match="Clip not found."):
        recordings.get_clip(library, "clip-nope")


# --- Zones --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "problem"),
    [("", "must not be blank"), (" \t ", "must not be blank"), ("n" * 61, "at most 60")],
)
def test_zone_names_are_checked(name: str, problem: str) -> None:
    with pytest.raises(InvalidInputError, match=problem) as caught:
        zones.check_zone_name(name)
    assert caught.value.field == "name"


def test_zone_names_are_trimmed() -> None:
    assert zones.check_zone_name("  Bay 3 ") == "Bay 3"


@pytest.mark.parametrize(
    "points",
    [
        TRIANGLE[:2],
        [(0.5, 0.5)] * 51,
        [(0.1,), (0.2, 0.2), (0.3, 0.3)],
        [(0.1, 0.1, 0.1), (0.2, 0.2), (0.3, 0.3)],
        [(float("nan"), 0.1), (0.2, 0.2), (0.3, 0.3)],
        [(float("inf"), 0.1), (0.2, 0.2), (0.3, 0.3)],
        [(1.01, 0.1), (0.2, 0.2), (0.3, 0.3)],
        [(-0.01, 0.1), (0.2, 0.2), (0.3, 0.3)],
        [("a", 0.1), (0.2, 0.2), (0.3, 0.3)],
    ],
)
def test_zone_points_are_checked(points: list[tuple[object, ...]]) -> None:
    with pytest.raises(InvalidInputError) as caught:
        zones.check_zone_points(points)  # type: ignore[arg-type]
    assert caught.value.field == "points"


def test_good_zone_points_come_back_as_float_pairs() -> None:
    assert zones.check_zone_points([[0, 1], [1, 0], [0.5, 0.5]]) == (
        (0.0, 1.0),
        (1.0, 0.0),
        (0.5, 0.5),
    )


def test_creating_zones(library: Library, store: InMemoryLibrary) -> None:
    zone = zones.create_zone(library, "CAM-001", " Bay ", TRIANGLE, make_id=lambda p: "z-1")
    assert zone == Zone(id="z-1", camera="CAM-001", name="Bay", points=tuple(TRIANGLE))
    assert store.zones["z-1"] == zone
    with pytest.raises(ZoneNameTakenError):
        zones.create_zone(library, "CAM-001", "BAY", TRIANGLE)
    with pytest.raises(NotFoundError):
        zones.create_zone(library, "garage", "Bay", TRIANGLE)


def test_the_fake_store_compares_zone_names_ignoring_case_like_the_port(
    store: InMemoryLibrary,
) -> None:
    lane = store.zones["zone-exit-lane"]
    with pytest.raises(DuplicateError):
        store.add_zone(replace(lane, id="zone-shouting", name="EXIT LANE"))
    with pytest.raises(DuplicateError):
        store.replace_zone(replace(lane, name="LOADING DOOR"))
    assert store.replace_zone(replace(lane, name="exit LANE")) is True
    assert store.zones["zone-exit-lane"].name == "exit LANE"


def test_a_zone_name_taken_in_a_race_is_still_409(
    store: InMemoryLibrary, library: Library, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_zone = store.add_zone

    def racing(zone: Zone) -> None:
        add_zone(replace(zone, id="zone-other"))  # another request got there first
        raise DuplicateError("name taken")

    monkeypatch.setattr(store, "add_zone", racing)
    with pytest.raises(ZoneNameTakenError):
        zones.create_zone(library, "CAM-001", "Bay", TRIANGLE)


def test_an_unexplained_duplicate_is_not_hidden(
    store: InMemoryLibrary, library: Library, monkeypatch: pytest.MonkeyPatch
) -> None:
    def clashing(zone: Zone) -> None:
        raise DuplicateError("id taken")

    monkeypatch.setattr(store, "add_zone", clashing)
    with pytest.raises(DuplicateError):
        zones.create_zone(library, "CAM-001", "Bay", TRIANGLE)


def test_replacing_and_deleting_zones(library: Library) -> None:
    replaced = zones.replace_zone(library, "zone-exit-lane", "Lane", TRIANGLE)
    assert (replaced.camera, replaced.name) == ("CAM-001", "Lane")
    with pytest.raises(ZoneNameTakenError):
        zones.replace_zone(library, "zone-exit-lane", "loading door", TRIANGLE)
    with pytest.raises(NotFoundError):
        zones.replace_zone(library, "zone-nope", "Lane", TRIANGLE)
    zones.delete_zone(library, "zone-exit-lane")
    with pytest.raises(NotFoundError):
        zones.delete_zone(library, "zone-exit-lane")


def test_a_zone_deleted_while_being_replaced_is_not_found(
    store: InMemoryLibrary, library: Library, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "replace_zone", lambda zone: False)
    with pytest.raises(NotFoundError):
        zones.replace_zone(library, "zone-exit-lane", "Lane", TRIANGLE)


# --- Saved clips --------------------------------------------------------------------------------


def test_saving_stamps_utc_to_the_second(library: Library) -> None:
    india = timezone(timedelta(hours=5, minutes=30))
    now = datetime(2026, 10, 30, 14, 42, 44, 999999, tzinfo=india)
    saved = saved_clips.save_clip(library, "clip-1029-104215", "note", now, make_id=lambda p: "s-1")
    assert saved.saved.saved_at == datetime(2026, 10, 30, 9, 12, 44, tzinfo=UTC)
    assert saved.saved.saved_at.utcoffset() == timedelta(0)
    assert saved.camera == "CAM-001"
    with pytest.raises(AlreadySavedError):
        saved_clips.save_clip(library, "clip-1029-104215", "", now)
    with pytest.raises(NotFoundError):
        saved_clips.save_clip(library, "clip-nope", "", now)
    with pytest.raises(InvalidInputError, match="note: must be at most 500"):
        saved_clips.save_clip(library, "clip-1029-061405", "n" * 501, now)


def test_saving_needs_an_aware_clock(library: Library) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        saved_clips.save_clip(library, "clip-1029-104215", "", datetime(2026, 10, 30, 9, 0))


def test_saved_clips_are_listed_newest_first_then_by_id(library: Library) -> None:
    moment = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
    for saved_id, clip_id, minutes in [
        ("s-b", "clip-1029-061405", 0),
        ("s-a", "clip-1029-070903", 0),
        ("s-c", "clip-1028-064712", 5),
    ]:
        saved_clips.save_clip(
            library,
            clip_id,
            "",
            moment + timedelta(minutes=minutes),
            make_id=lambda p, i=saved_id: i,
        )
    listed = saved_clips.list_saved_clips(library)
    assert [s.saved.id for s in listed] == ["s-c", "s-a", "s-b"]
    assert {s.camera for s in listed} == {"CAM-001"}
    on_thursday = saved_clips.list_saved_clips(library, THURSDAY)
    assert [s.saved.id for s in on_thursday] == ["s-a", "s-b"]


def test_notes_are_updated_and_saved_clips_removed(library: Library) -> None:
    now = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
    saved_clips.save_clip(library, "clip-1029-104215", "", now, make_id=lambda p: "s-1")
    assert saved_clips.update_note(library, "s-1", "checked").saved.note == "checked"
    with pytest.raises(NotFoundError):
        saved_clips.update_note(library, "s-nope", "x")
    with pytest.raises(InvalidInputError):
        saved_clips.update_note(library, "s-1", "n" * 501)
    saved_clips.delete_saved_clip(library, "s-1")
    with pytest.raises(NotFoundError):
        saved_clips.delete_saved_clip(library, "s-1")


# --- Ids and layering ---------------------------------------------------------------------------


def test_new_ids_are_prefixed_unique_and_fit_the_id_pattern() -> None:
    made = {new_id("zone") for _ in range(200)}
    assert len(made) == 200
    assert all(len(i) == len("zone-") + 12 and i.startswith("zone-") for i in made)


def _imports(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.mark.parametrize(
    "source",
    sorted((REPO_ROOT / "askfootage" / "application").glob("*.py")),
    ids=lambda path: path.name,
)
def test_the_application_layer_never_imports_adapters_or_interfaces(source: Path) -> None:
    forbidden = {"askfootage.adapters", "askfootage.interfaces", "fastapi", "starlette"}
    assert not {name for name in _imports(source) if any(name.startswith(f) for f in forbidden)}


def test_only_the_app_factory_imports_the_sqlite_adapter() -> None:
    api_dir = REPO_ROOT / "askfootage" / "interfaces" / "api"
    importers = sorted(
        path.name
        for path in api_dir.glob("*.py")
        if any(name.startswith("askfootage.adapters") for name in _imports(path))
    )
    assert importers == ["app.py"]
