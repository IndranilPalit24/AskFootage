"""The generated demo volume: determinism, geometry, day counts, add, remove, real rows safe.

Every database lives in pytest's tmp_path; nothing here touches data/.
"""

import re
import sqlite3
from collections import Counter
from datetime import date, timedelta

import pytest
from db_library_helpers import (
    CREATED_AT,
    DEMO_SEED,
    clip,
    dump,
    new_camera,
    raw_connection,
    recording,
)

from askfootage.adapters.sqlite import volume_seed
from askfootage.adapters.sqlite.store import SqliteLibraryStore, seed_demo_data
from askfootage.adapters.sqlite.volume_seed import (
    CAMERA_COUNT,
    DEMO_DAY,
    VOLUME_DAYS,
    VOLUME_ORIGIN,
    add_volume,
    generate_volume,
    remove_volume,
    volume_status,
)
from askfootage.application.library import Library
from askfootage.application.recordings import list_days
from askfootage.ports.library_store import LibraryError, Recording, Zone

DAYS = [DEMO_DAY - timedelta(days=offset) for offset in range(VOLUME_DAYS - 1, -1, -1)]


@pytest.fixture
def volume_data():  # noqa: ANN201 - a VolumeData
    """The volume numbered from CAM-002, as it lands next to one real camera."""
    return generate_volume(2)


@pytest.fixture
def real_store(store: SqliteLibraryStore) -> SqliteLibraryStore:
    """A library shaped like the real one: one camera, two ready recordings, one clip."""
    store.add_camera(new_camera("Real clips (replayed)"))
    store.add_recording(recording("clip1", day=DEMO_DAY))
    store.add_recording(recording("clip2", day=DEMO_DAY))
    store.add_clip(clip("rel-1", recording_id="clip2", day=DEMO_DAY))
    return store


# --- The generator ---------------------------------------------------------------------------


def test_the_generator_is_deterministic_run_to_run() -> None:
    assert generate_volume(2) == generate_volume(2)
    assert repr(generate_volume(2)) == repr(generate_volume(2))


def test_the_generator_is_the_same_whatever_the_first_camera_number_but_for_ids() -> None:
    low, high = generate_volume(2), generate_volume(40)
    assert [(c.name, c.location, c.status) for c in low.cameras] == [
        (c.name, c.location, c.status) for c in high.cameras
    ]
    assert [(r.day, r.start_time, r.status) for r in low.recordings] == [
        (r.day, r.start_time, r.status) for r in high.recordings
    ]


def test_cameras_continue_the_numbering_and_have_factory_names(volume_data) -> None:  # noqa: ANN001
    cameras = volume_data.cameras
    assert 14 <= len(cameras) == CAMERA_COUNT <= 20
    assert [c.id for c in cameras] == [f"CAM-{n:03d}" for n in range(2, 2 + len(cameras))]
    assert len({c.name.casefold() for c in cameras}) == len(cameras)
    assert all(c.location and c.department for c in cameras)
    names = " ".join(c.name for c in cameras)
    for word in ("Loading Bay", "Packaging Line", "Exit Lane", "Yard Gate", "Dispatch Door"):
        assert word in names
    for word in ("Warehouse Aisle", "Goods-In", "Maintenance Bay"):
        assert word in names


def test_camera_statuses_are_mostly_online_two_standby_and_one_or_two_offline(
    volume_data,  # noqa: ANN001
) -> None:
    counts = Counter(c.status for c in volume_data.cameras)
    assert counts["standby"] == 2
    assert counts["offline"] in (1, 2)
    assert counts["online"] > len(volume_data.cameras) / 2


def test_cameras_are_generic_and_carry_no_identity_or_vendor_words(volume_data) -> None:  # noqa: ANN001
    text = repr(volume_data).lower()
    for word in (
        "meta",
        "sam",
        "llama",
        "openai",
        "google",
        "amazon",
        "microsoft",
        "acme",
        "ltd",
        "inc.",
        "gmbh",
        "face",
        "name:",
    ):
        assert re.search(rf"\b{re.escape(word)}\b", text) is None, word
    assert {c.username for c in volume_data.cameras} == {"viewer"}
    assert all(c.ip.startswith("198.51.100.") for c in volume_data.cameras)


def _area(points: tuple[tuple[float, float], ...]) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, (*points[1:], points[0]), strict=True):
        total += x1 * y2 - x2 * y1
    return total / 2


def _cross(o, a, b) -> float:  # noqa: ANN001
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def test_most_cameras_have_two_to_five_zones_with_unique_names(volume_data) -> None:  # noqa: ANN001
    per_camera = Counter(zone.camera for zone in volume_data.zones)
    with_zones = [c.id for c in volume_data.cameras if per_camera[c.id]]
    assert len(with_zones) > len(volume_data.cameras) * 0.75
    assert all(2 <= per_camera[camera] <= 5 for camera in with_zones)
    for camera in with_zones:
        names = [z.name.casefold() for z in volume_data.zones if z.camera == camera]
        assert len(set(names)) == len(names)
    assert len({z.id for z in volume_data.zones}) == len(volume_data.zones)


def test_every_zone_is_a_valid_non_degenerate_convex_polygon_inside_the_frame(
    volume_data,  # noqa: ANN001
) -> None:
    assert volume_data.zones
    for zone in volume_data.zones:
        points = zone.points
        assert len(points) >= 3 and len(set(points)) == len(points)
        assert all(0 <= x <= 1 and 0 <= y <= 1 for x, y in points)
        assert abs(_area(points)) > 0.02, zone.id
        turns = [
            _cross(points[i], points[(i + 1) % len(points)], points[(i + 2) % len(points)])
            for i in range(len(points))
        ]
        assert all(t > 0 for t in turns) or all(t < 0 for t in turns), zone.id  # convex


def test_zones_of_one_camera_do_not_overlap(volume_data) -> None:  # noqa: ANN001
    for camera in volume_data.cameras:
        boxes = []
        for zone in (z for z in volume_data.zones if z.camera == camera.id):
            xs, ys = [p[0] for p in zone.points], [p[1] for p in zone.points]
            boxes.append((min(xs), max(xs), min(ys), max(ys)))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                assert a[1] <= b[0] or b[1] <= a[0] or a[3] <= b[2] or b[3] <= a[2]


def test_every_camera_has_recordings_on_each_day_it_was_recording(volume_data) -> None:  # noqa: ANN001
    days_of = {
        c.id: {r.day for r in volume_data.recordings if r.camera == c.id}
        for c in volume_data.cameras
    }
    assert {r.day for r in volume_data.recordings} == set(DAYS)
    assert max(max(days) for days in days_of.values()) == DEMO_DAY
    for camera in volume_data.cameras:
        assert days_of[camera.id], camera.name  # nobody is empty
        if camera.status == "online":
            assert len(days_of[camera.id]) >= 6  # all but at most a Sunday


def test_recordings_have_realistic_starts_lengths_and_do_not_overlap(volume_data) -> None:  # noqa: ANN001
    assert all(15 * 60 <= r.length_seconds <= 60 * 60 for r in volume_data.recordings)
    assert all(r.length_seconds % 60 == 0 for r in volume_data.recordings)
    seen: dict[tuple[str, date], list[tuple[int, int]]] = {}
    for r in volume_data.recordings:
        start = r.start_time.hour * 3600 + r.start_time.minute * 60 + r.start_time.second
        assert 5 * 3600 <= start and start + r.length_seconds <= 23 * 3600
        seen.setdefault((r.camera, r.day), []).append((start, start + r.length_seconds))
    for spans in seen.values():
        spans.sort()
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))


def test_recordings_are_mostly_ready_with_a_few_processing_and_a_few_failed(
    volume_data,  # noqa: ANN001
) -> None:
    recordings = volume_data.recordings
    counts = Counter(r.status for r in recordings)
    failed = [r for r in recordings if r.status_note]
    processing = [r for r in recordings if r.status in ("preparing", "indexing")]
    assert counts["ready"] > 0.9 * len(recordings)
    assert 3 <= len(failed) <= 0.03 * len(recordings)
    assert 3 <= len(processing) <= 0.05 * len(recordings)
    assert all(r.status == "waiting" for r in failed)  # a failed pass goes back to waiting
    assert all(len(r.status_note or "") > 10 for r in failed)
    assert all(r.status_note is None for r in recordings if r.status != "waiting")
    assert {r.day for r in processing} == {DEMO_DAY}  # only the newest day is in progress


def test_generated_recordings_have_no_footage_and_ids_do_not_clash(volume_data) -> None:  # noqa: ANN001
    assert all(r.has_footage is False for r in volume_data.recordings)
    ids = [r.id for r in volume_data.recordings]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(r"vr-\d{3}-\d{8}-\d{4}", i) for i in ids)
    assert not any(i in ("clip1", "clip2") or i.startswith("rec-") for i in ids)


def test_a_camera_name_that_is_taken_gets_a_suffix() -> None:
    data = generate_volume(2, taken_camera_names=["loading bay 1", "MAINTENANCE BAY"])
    names = [c.name for c in data.cameras]
    assert "Loading Bay 1 (2)" in names and "Maintenance Bay (2)" in names
    assert len({n.casefold() for n in names}) == len(names)


def test_the_first_camera_number_must_be_positive() -> None:
    with pytest.raises(ValueError):
        generate_volume(0)


def test_the_volume_ends_on_the_demo_days_today() -> None:
    import json

    seed = json.loads(DEMO_SEED.read_text(encoding="utf-8"))
    assert date.fromisoformat(seed["today"]) == DEMO_DAY


def test_the_generator_makes_no_clips_tracks_or_saved_clips(volume_data) -> None:  # noqa: ANN001
    assert set(volume_data.__slots__) == {"cameras", "zones", "recordings"}


# --- Adding ----------------------------------------------------------------------------------


def test_add_writes_every_row_tagged_demo_volume(real_store: SqliteLibraryStore) -> None:
    assert add_volume(real_store) is True
    data = generate_volume(2)
    status = volume_status(real_store)
    assert status["cameras"] == {"real": 1, VOLUME_ORIGIN: len(data.cameras)}
    assert status["zones"] == {"real": 0, VOLUME_ORIGIN: len(data.zones)}
    assert status["recordings"] == {"real": 2, VOLUME_ORIGIN: len(data.recordings)}
    assert status["zone_points"][VOLUME_ORIGIN] == sum(len(z.points) for z in data.zones)
    with raw_connection(real_store.path) as db:
        assert db.execute("SELECT count(*) FROM cameras WHERE origin = 'real'").fetchone()[0] == 1
        assert (
            db.execute("SELECT count(*) FROM recordings WHERE has_footage = 1").fetchone()[0] == 2
        )


def test_add_creates_no_clips_tracks_saved_clips_or_markers(real_store: SqliteLibraryStore) -> None:
    before = volume_status(real_store)
    add_volume(real_store)
    after = volume_status(real_store)
    for table in (
        "clips",
        "clip_evidence",
        "clip_key_frames",
        "saved_clips",
        "tracks",
        "track_points",
        "concepts_searched",
    ):
        assert after[table][VOLUME_ORIGIN] == 0, table
        assert after[table]["real"] == before[table]["real"], table


def test_volume_rows_round_trip_through_the_store(real_store: SqliteLibraryStore) -> None:
    add_volume(real_store)
    data = generate_volume(2)
    assert real_store.list_cameras()[1:] == list(data.cameras)
    for zone in data.zones[:5]:
        assert real_store.get_zone(zone.id) == zone
    sample = data.recordings[len(data.recordings) // 2]
    assert real_store.get_recording(sample.id) == sample
    assert real_store.get_recording(sample.id).has_footage is False  # type: ignore[union-attr]


def test_adding_twice_changes_nothing(real_store: SqliteLibraryStore) -> None:
    assert add_volume(real_store) is True
    first = dump(real_store.path)
    assert add_volume(real_store) is False
    assert dump(real_store.path) == first


def test_add_does_not_change_any_real_row(real_store: SqliteLibraryStore) -> None:
    def real_rows() -> dict[str, list[object]]:
        with raw_connection(real_store.path) as db:
            return {
                "cameras": db.execute("SELECT * FROM cameras WHERE origin = 'real'").fetchall(),
                "recordings": db.execute(
                    "SELECT * FROM recordings WHERE origin = 'real'"
                ).fetchall(),
                "clips": db.execute("SELECT * FROM clips").fetchall(),
                "evidence": db.execute("SELECT * FROM clip_evidence").fetchall(),
            }

    before = real_rows()
    add_volume(real_store)
    assert real_rows() == before


def test_the_next_camera_after_the_volume_continues_the_numbering(
    real_store: SqliteLibraryStore,
) -> None:
    add_volume(real_store)
    last = real_store.list_cameras()[-1].id
    added = real_store.add_camera(new_camera("Visitor Lobby"))
    assert int(added.id[4:]) == int(last[4:]) + 1


def test_add_works_after_the_demo_seed_and_continues_from_cam_004(
    store: SqliteLibraryStore,
) -> None:
    assert seed_demo_data(store, DEMO_SEED) is True
    before = dump(store.path)
    add_volume(store)
    assert store.list_cameras()[3].id == "CAM-004"
    assert remove_volume(store) == CAMERA_COUNT
    assert dump(store.path) == before


def test_add_to_an_empty_library_starts_at_cam_001(store: SqliteLibraryStore) -> None:
    add_volume(store)
    assert store.list_cameras()[0].id == "CAM-001"
    assert remove_volume(store) == CAMERA_COUNT
    assert store.add_camera(new_camera("First")).id == "CAM-001"


def test_a_name_clash_with_a_real_camera_is_resolved_not_refused(store: SqliteLibraryStore) -> None:
    store.add_camera(new_camera("yard gate north"))
    assert add_volume(store) is True
    assert "Yard Gate North (2)" in [c.name for c in store.list_cameras()]


def test_a_failed_add_leaves_the_database_unchanged(
    real_store: SqliteLibraryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = dump(real_store.path)

    def explode(*_: object) -> None:
        raise LibraryError("boom")

    monkeypatch.setattr(volume_seed, "_insert_recording", explode)
    with pytest.raises(LibraryError):
        add_volume(real_store)
    assert dump(real_store.path) == before


# --- Day counts match what /api/days reports ----------------------------------------------------


def test_day_counts_are_what_the_days_endpoint_reports(real_store: SqliteLibraryStore) -> None:
    add_volume(real_store)
    data = generate_volume(2)
    library = Library.from_store(real_store)
    reported = {item.day: item for item in list_days(library, None, DEMO_DAY)}
    assert list(reported) == DAYS
    for day in DAYS:
        mine = [r for r in data.recordings if r.day == day]
        real = 2 if day == DEMO_DAY else 0  # clip1 and clip2 sit on the demo day
        assert reported[day].recordings == len(mine) + real
        assert reported[day].ready == sum(1 for r in mine if r.status == "ready") + real
    for camera in data.cameras:
        per_camera = {item.day: item for item in list_days(library, camera.id, DEMO_DAY)}
        for day, summary in per_camera.items():
            mine = [r for r in data.recordings if r.camera == camera.id and r.day == day]
            assert summary.recordings == len(mine)
        assert sum(s.recordings for s in per_camera.values()) == sum(
            1 for r in data.recordings if r.camera == camera.id
        )


def test_list_recordings_on_the_demo_day_has_the_volume_in_start_order(
    real_store: SqliteLibraryStore,
) -> None:
    add_volume(real_store)
    listed = real_store.list_recordings(None, DEMO_DAY)
    starts = [r.start_time for r in listed]
    assert starts == sorted(starts)
    assert {"clip1", "clip2"} <= {r.id for r in listed}
    assert {r.id: r.has_footage for r in listed}["clip1"] is True


# --- Removing --------------------------------------------------------------------------------


def test_remove_restores_the_database_exactly(real_store: SqliteLibraryStore) -> None:
    before = dump(real_store.path)
    add_volume(real_store)
    assert dump(real_store.path) != before
    assert remove_volume(real_store) == CAMERA_COUNT
    assert dump(real_store.path) == before  # every row, the counter and the schema text


def test_remove_restores_the_camera_counter(real_store: SqliteLibraryStore) -> None:
    add_volume(real_store)
    remove_volume(real_store)
    assert real_store.add_camera(new_camera("Visitor Lobby")).id == "CAM-002"


def test_remove_keeps_the_counter_guard_trigger(real_store: SqliteLibraryStore) -> None:
    add_volume(real_store)
    remove_volume(real_store)
    with raw_connection(real_store.path) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM sqlite_schema WHERE name = 'camera_sequence_never_goes_back'"
            ).fetchone()[0]
            == 1
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE camera_sequence SET last_number = 0")


def test_remove_with_no_volume_changes_nothing(real_store: SqliteLibraryStore) -> None:
    before = dump(real_store.path)
    assert remove_volume(real_store) == 0
    assert dump(real_store.path) == before


def test_add_remove_add_gives_the_same_volume_again(real_store: SqliteLibraryStore) -> None:
    add_volume(real_store)
    first = dump(real_store.path)
    remove_volume(real_store)
    add_volume(real_store)
    assert dump(real_store.path) == first


def test_remove_leaves_no_orphans(real_store: SqliteLibraryStore) -> None:
    add_volume(real_store)
    remove_volume(real_store)
    with raw_connection(real_store.path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT count(*) FROM zone_points").fetchone()[0] == 0
        for table in ("cameras", "zones", "recordings"):
            n = db.execute(f"SELECT count(*) FROM {table} WHERE origin = 'demo_volume'").fetchone()  # noqa: S608
            assert n[0] == 0


def test_remove_refuses_when_a_clip_was_saved_from_a_volume_recording(
    real_store: SqliteLibraryStore,
) -> None:
    add_volume(real_store)
    volume_recording = generate_volume(2).recordings[0]
    real_store.add_clip(clip("mine", recording_id=volume_recording.id, day=volume_recording.day))
    real_store.add_saved_clip("save-1", "mine", "keep", CREATED_AT)
    before = dump(real_store.path)
    with pytest.raises(LibraryError, match="saved clip"):
        remove_volume(real_store)
    assert dump(real_store.path) == before


def test_remove_refuses_when_a_real_recording_was_added_to_a_volume_camera(
    real_store: SqliteLibraryStore,
) -> None:
    add_volume(real_store)
    camera = generate_volume(2).cameras[0].id
    real_store.add_recording(
        Recording("upload-1", camera, DEMO_DAY, recording().start_time, 60, "waiting")
    )
    before = dump(real_store.path)
    with pytest.raises(LibraryError, match="added to one of its"):
        remove_volume(real_store)
    assert dump(real_store.path) == before


def test_remove_does_not_touch_a_real_camera_added_after_the_volume(
    real_store: SqliteLibraryStore,
) -> None:
    add_volume(real_store)
    mine = real_store.add_camera(new_camera("Visitor Lobby"))
    remove_volume(real_store)
    assert [c.id for c in real_store.list_cameras()] == ["CAM-001", mine.id]
    assert real_store.add_camera(new_camera("Another")).id == f"CAM-{int(mine.id[4:]) + 1:03d}"


# --- Constraints of the new columns ------------------------------------------------------------


def test_origin_and_has_footage_reject_bad_values(real_store: SqliteLibraryStore) -> None:
    real_store.add_zone(Zone("z1", "CAM-001", "Gate", ((0.1, 0.1), (0.5, 0.1), (0.5, 0.5))))
    with raw_connection(real_store.path) as db:
        for sql in (
            "UPDATE cameras SET origin = 'fake'",
            "UPDATE zones SET origin = 'fake'",
            "UPDATE recordings SET origin = 'fake'",
            "UPDATE recordings SET origin = NULL",
            "UPDATE recordings SET has_footage = 2",
            "UPDATE recordings SET has_footage = NULL",
            "INSERT INTO volume_state VALUES (2, 1)",
            "INSERT INTO volume_state VALUES (1, -1)",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)


def test_new_rows_default_to_real_origin_with_footage(real_store: SqliteLibraryStore) -> None:
    real_store.add_zone(Zone("z1", "CAM-001", "Gate", ((0.1, 0.1), (0.5, 0.1), (0.5, 0.5))))
    with raw_connection(real_store.path) as db:
        assert db.execute("SELECT origin FROM cameras").fetchall() == [("real",)]
        assert db.execute("SELECT origin FROM zones").fetchall() == [("real",)]
        assert set(db.execute("SELECT origin, has_footage FROM recordings")) == {("real", 1)}


def test_has_footage_round_trips_through_add_recording(real_store: SqliteLibraryStore) -> None:
    without = Recording(
        "nofile", "CAM-001", DEMO_DAY, recording().start_time, 60, "ready", None, False
    )
    real_store.add_recording(without)
    assert real_store.get_recording("nofile") == without
    assert (
        Recording("a", "CAM-001", DEMO_DAY, recording().start_time, 1, "ready").has_footage is True
    )


def test_an_injection_string_in_a_status_note_is_still_plain_text(
    real_store: SqliteLibraryStore,
) -> None:
    add_volume(real_store)
    victim = generate_volume(2).recordings[0].id
    note = "x'); DROP TABLE recordings; --"
    real_store.set_recording_status(victim, "waiting", note=note)
    assert real_store.get_recording(victim).status_note == note  # type: ignore[union-attr]
    assert volume_status(real_store)["recordings"][VOLUME_ORIGIN] == len(
        generate_volume(2).recordings
    )


def test_status_lists_every_table_with_both_origins(real_store: SqliteLibraryStore) -> None:
    status = volume_status(real_store)
    assert all(set(counts) == {"real", VOLUME_ORIGIN} for counts in status.values())
    assert status["clips"]["real"] == 1
    assert status["cameras"] == {"real": 1, VOLUME_ORIGIN: 0}
