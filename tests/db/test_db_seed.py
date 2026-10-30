"""seed_demo_data: the demo library matches the contract examples, loads once, and a bad
seed leaves the database empty."""

import copy
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
from db_library_helpers import (
    DEMO_SEED,
    EXAMPLES_DIR,
    TABLES,
    camera,
    clip_json,
    count_rows,
    raw_connection,
    recording_json,
    saved_clip_json,
    zone_json,
)

from askfootage.adapters.sqlite import SeedDataError
from askfootage.adapters.sqlite.store import SqliteLibraryStore, seed_demo_data
from askfootage.ports.library_store import DaySummary

CAMERA = "loading-dock"
THURSDAY = date(2026, 10, 29)

# The design reference for Thu 29 Oct 2026, written out as literals rather than read from
# contract/examples, so an edit that changes the seed and the examples together still
# fails here. (id, start time, length in whole minutes, status), in list order.
THURSDAY_RECORDINGS = [
    ("rec-1029-0600", time(6, 0), 31, "ready"),
    ("rec-1029-0705", time(7, 5), 24, "ready"),
    ("rec-1029-0912", time(9, 12), 18, "ready"),
    ("rec-1029-1030", time(10, 30), 27, "ready"),
    ("rec-1029-1300", time(13, 0), 22, "ready"),
    ("rec-1029-1610", time(16, 10), 12, "indexing"),
]
THURSDAY_CLIPS = [
    "clip-1029-061405",
    "clip-1029-070903",
    "clip-1029-072140",
    "clip-1029-091522",
    "clip-1029-104215",
    "clip-1029-104847",
    "clip-1029-130610",
    "clip-1029-131430",
]
# Recordings and ready recordings per day, Sat 24 to Fri 30; Sun 25 has none.
WEEK = {24: (1, 1), 26: (2, 2), 27: (2, 2), 28: (3, 3), 29: (6, 5), 30: (4, 2)}


def _example(name: str) -> object:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


def _seed_document() -> dict:
    return json.loads(DEMO_SEED.read_text(encoding="utf-8"))


def _write_seed(directory: Path, document: object) -> Path:
    path = directory / "seed.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _snapshot(path: Path) -> dict[str, list[tuple[object, ...]]]:
    """Every row of every table, in a stable order."""
    with raw_connection(path) as db:
        return {
            table: sorted(db.execute(f"SELECT * FROM {table}").fetchall(), key=repr)
            for table in TABLES  # fixed table names from the schema, never input
        }


def test_seeding_loads_the_whole_demo_library(seeded_store: SqliteLibraryStore) -> None:
    assert [(c.id, c.name) for c in seeded_store.list_cameras()] == [(CAMERA, "Loading dock")]
    total = sum(
        len(seeded_store.list_recordings(CAMERA, date(2026, 10, day))) for day in range(24, 31)
    )
    assert total == 18
    thursday = seeded_store.list_recordings(CAMERA, THURSDAY)
    assert (len(thursday), sum(r.status == "ready" for r in thursday)) == (6, 5)
    friday = seeded_store.list_recordings(CAMERA, date(2026, 10, 30))
    assert (len(friday), sum(r.status == "ready" for r in friday)) == (4, 2)
    clips_per_day = {
        day: len(seeded_store.list_clips(CAMERA, date(2026, 10, day))) for day in range(24, 31)
    }
    assert clips_per_day == {24: 0, 25: 0, 26: 0, 27: 0, 28: 2, 29: 8, 30: 2}
    assert len(seeded_store.list_zones()) == 2
    assert seeded_store.list_saved_clips() == []


def test_thursday_matches_the_design_reference(seeded_store: SqliteLibraryStore) -> None:
    recordings = seeded_store.list_recordings(CAMERA, THURSDAY)
    assert [
        (r.id, r.camera, r.day, r.start_time, r.length_seconds, r.status) for r in recordings
    ] == [
        (rec_id, CAMERA, THURSDAY, start, minutes * 60, status)
        for rec_id, start, minutes, status in THURSDAY_RECORDINGS
    ]
    assert sum(r.length_seconds for r in recordings) == 134 * 60  # 2 h 14 min
    assert seeded_store.summarise_days(CAMERA, THURSDAY, THURSDAY) == [
        DaySummary(day=THURSDAY, recordings=6, ready=5)
    ]

    clips = seeded_store.list_clips(CAMERA, THURSDAY)
    assert [c.id for c in clips] == THURSDAY_CLIPS
    on_thursday = {r.id: r for r in recordings}
    for found in clips:
        recording = on_thursday[found.recording_id]
        assert recording.status == "ready", found.id
        assert found.day == THURSDAY, found.id
        assert 0 <= found.start_seconds < found.end_seconds <= recording.length_seconds, found.id

    assert [z.name for z in seeded_store.list_zones(CAMERA)] == ["Exit lane", "Loading door"]
    assert seeded_store.list_saved_clips() == []
    assert seeded_store.list_saved_clips(THURSDAY) == []


def test_the_seeded_week_runs_saturday_to_friday_with_today_on_friday(
    seeded_store: SqliteLibraryStore,
) -> None:
    first, last = date(2026, 10, 24), date(2026, 10, 30)
    # weekday(): Monday is 0, so Saturday 5, Thursday 3, Friday 4 (locale-independent).
    assert (first.weekday(), THURSDAY.weekday(), last.weekday()) == (5, 3, 4)
    assert _seed_document()["today"] == last.isoformat()
    assert seeded_store.summarise_days(CAMERA, first, last) == [
        DaySummary(day=date(2026, 10, day), recordings=count, ready=ready)
        for day, (count, ready) in WEEK.items()
    ]
    assert sum(count for count, _ in WEEK.values()) == 18
    # Nothing was seeded outside the week.
    assert seeded_store.summarise_days(CAMERA, date(2000, 1, 1), date(2026, 10, 23)) == []
    assert seeded_store.summarise_days(CAMERA, date(2026, 10, 31), date(2100, 1, 1)) == []


def test_every_seeded_clip_lies_inside_a_ready_recording_and_agrees_with_it(
    seeded_store: SqliteLibraryStore,
) -> None:
    zone_names = {z.name for z in seeded_store.list_zones()}
    clips = [
        found
        for offset in range(7)
        for found in seeded_store.list_clips(CAMERA, date(2026, 10, 24) + timedelta(days=offset))
    ]
    assert len(clips) == 12
    for found in clips:
        recording = seeded_store.get_recording(found.recording_id)
        assert recording is not None, found.id
        assert (recording.camera, recording.day, recording.status) == (
            CAMERA,
            found.day,
            "ready",
        ), found.id
        assert found.end_seconds <= recording.length_seconds, found.id
        # start_time is the wall-clock time at start_seconds into the recording.
        opened = datetime.combine(found.day, recording.start_time)
        assert (opened + timedelta(seconds=found.start_seconds)).time() == found.start_time
        moments = [frame.at_seconds for frame in found.key_frames]
        assert moments == sorted(moments), found.id
        assert all(found.start_seconds <= at <= found.end_seconds for at in moments), found.id
        assert found.zone is None or found.zone in zone_names, found.id
        assert found.evidence, found.id


def test_row_counts_after_seeding(seeded_store: SqliteLibraryStore, library_path: Path) -> None:
    counts = {table: count_rows(library_path, table) for table in TABLES}
    assert counts == {
        "cameras": 1,
        "recordings": 18,
        "clips": 12,
        "clip_evidence": 23,
        "clip_key_frames": 36,
        "zones": 2,
        "zone_points": 8,
        "saved_clips": 0,
    }


def test_summarise_days_matches_the_days_example(seeded_store: SqliteLibraryStore) -> None:
    days = _example("days.json")
    assert isinstance(days, list)
    expected = [day for day in days if day["recordings"] > 0]
    summary = seeded_store.summarise_days(CAMERA, date(2026, 10, 24), date(2026, 10, 30))
    got = [
        {"day": s.day.isoformat(), "recordings": s.recordings, "ready": s.ready} for s in summary
    ]
    assert got == expected


def test_list_recordings_matches_the_recordings_example(seeded_store: SqliteLibraryStore) -> None:
    got = [recording_json(r) for r in seeded_store.list_recordings(CAMERA, THURSDAY)]
    assert got == _example("recordings.json")


def test_get_clip_matches_the_clip_detail_example(seeded_store: SqliteLibraryStore) -> None:
    got = seeded_store.get_clip("clip-1029-104215")
    assert got is not None
    assert clip_json(got) == _example("clip-detail.json")


def test_every_seeded_clip_and_recording_reads_back_as_written(
    seeded_store: SqliteLibraryStore,
) -> None:
    document = _seed_document()
    for written in document["clips"]:
        stored = seeded_store.get_clip(written["id"])
        assert stored is not None and clip_json(stored) == written
    for written in document["recordings"]:
        stored = seeded_store.get_recording(written["id"])
        assert stored is not None
        assert {**recording_json(stored), "camera": stored.camera} == written


def test_zones_match_the_zones_example_in_name_order(seeded_store: SqliteLibraryStore) -> None:
    # zones.json lists "Loading door" first; the Protocol orders zones by name, then id.
    zones = _example("zones.json")
    assert isinstance(zones, list)
    expected = sorted(zones, key=lambda z: (z["name"], z["id"]))
    assert [zone_json(z) for z in seeded_store.list_zones()] == expected
    assert [zone_json(z) for z in seeded_store.list_zones(CAMERA)] == expected


def test_a_saved_clip_matches_the_saved_clips_example(seeded_store: SqliteLibraryStore) -> None:
    saved = seeded_store.add_saved_clip(
        "saved-7f3c2a9e",
        "clip-1029-104215",
        "Check this delivery against the paperwork",
        datetime(2026, 10, 30, 9, 12, 44, tzinfo=UTC),
    )
    expected = _example("saved-clips.json")
    assert [saved_clip_json(saved)] == expected
    assert [saved_clip_json(s) for s in seeded_store.list_saved_clips(THURSDAY)] == expected


def test_seeding_again_returns_false_and_changes_nothing(
    seeded_store: SqliteLibraryStore, library_path: Path
) -> None:
    before = _snapshot(library_path)
    assert seed_demo_data(seeded_store, DEMO_SEED) is False
    assert seed_demo_data(SqliteLibraryStore(library_path), DEMO_SEED) is False
    assert _snapshot(library_path) == before


def test_a_restart_does_not_bring_back_a_deleted_zone(
    seeded_store: SqliteLibraryStore, library_path: Path
) -> None:
    assert seeded_store.delete_zone("zone-exit-lane") is True

    restarted = SqliteLibraryStore(library_path)
    assert seed_demo_data(restarted, DEMO_SEED) is False

    assert [z.id for z in restarted.list_zones()] == ["zone-loading-door"]


def test_any_camera_at_all_blocks_seeding(store: SqliteLibraryStore, library_path: Path) -> None:
    store.add_camera(camera("other-camera", "Other"))
    assert seed_demo_data(store, DEMO_SEED) is False
    assert count_rows(library_path, "recordings") == 0


def _drop_key(document: dict, path: tuple[object, ...]) -> None:
    *parents, last = path
    target = document
    for key in parents:
        target = target[key]
    del target[last]


def _set_value(document: dict, path: tuple[object, ...], value: object) -> None:
    *parents, last = path
    target = document
    for key in parents:
        target = target[key]
    target[last] = value


_BAD_VALUES = {
    "recording-start-time": (("recordings", 0, "startTime"), "8:00"),
    "recording-day": (("recordings", 0, "day"), "2026-10-32"),
    "recording-day-compact": (("recordings", 0, "day"), "20261024"),
    "recording-length-text": (("recordings", 0, "lengthSeconds"), "14400"),
    "recording-length-bool": (("recordings", 0, "lengthSeconds"), True),
    "recording-length-float": (("recordings", 0, "lengthSeconds"), 14400.5),
    "recording-status": (("recordings", 0, "status"), "done"),
    "recording-camera-unknown": (("recordings", 17, "camera"), "no-such-camera"),
    "clip-recording-unknown": (("clips", 11, "recordingId"), "rec-nope"),
    "clip-day-not-its-recordings": (("clips", 11, "day"), "2026-10-29"),
    "clip-end-before-start": (("clips", 0, "endSeconds"), 1),
    "clip-evidence-kind": (("clips", 0, "evidence", 0, "kind"), "face"),
    "clip-key-frames-not-list": (("clips", 0, "keyFrames"), {"atSeconds": 1}),
    "clip-zone-number": (("clips", 0, "zone"), 7),
    "clip-repeated-id": (("clips", 11, "id"), "clip-1028-064712"),
    "zone-point-out-of-frame": (("zones", 1, "points", 0), [1.5, 0.5]),
    "zone-point-three-numbers": (("zones", 1, "points", 0), [0.1, 0.2, 0.3]),
    "zone-two-points": (("zones", 1, "points"), [[0, 0], [1, 1]]),
    "zone-name-taken": (("zones", 1, "name"), "Loading door"),
    "zone-name-taken-other-case": (("zones", 1, "name"), "LOADING DOOR"),
    "zone-name-too-long": (("zones", 1, "name"), "x" * 61),
    "camera-id": (("cameras", 0, "id"), "loading dock"),
    "cameras-not-list": (("cameras",), {"id": "loading-dock"}),
    "saved-clip-unknown-clip": (
        ("savedClips",),
        [{"id": "s-1", "clipId": "clip-nope", "note": "", "savedAt": "2026-10-30T09:00:00Z"}],
    ),
    "saved-clip-naive-time": (
        ("savedClips",),
        [{"id": "s-1", "clipId": "clip-1029-104215", "note": "", "savedAt": "2026-10-30T09:00"}],
    ),
}


@pytest.mark.parametrize("case", sorted(_BAD_VALUES))
def test_a_malformed_seed_raises_and_leaves_the_database_empty(
    store: SqliteLibraryStore, library_path: Path, tmp_path: Path, case: str
) -> None:
    document = _seed_document()
    path, value = _BAD_VALUES[case]
    _set_value(document, path, value)
    seed_file = _write_seed(tmp_path, document)

    with pytest.raises(SeedDataError) as refused:
        seed_demo_data(store, seed_file)

    assert str(tmp_path) not in str(refused.value)
    assert {table: count_rows(library_path, table) for table in TABLES} == dict.fromkeys(TABLES, 0)
    # Nothing was half-written: the real seed still loads into the same file.
    assert seed_demo_data(store, DEMO_SEED) is True


@pytest.mark.parametrize(
    "path",
    [("cameras",), ("recordings",), ("clips",), ("zones",), ("clips", 0, "whyMatched")],
    ids=lambda p: ".".join(map(str, p)),
)
def test_a_seed_missing_a_required_key_is_refused(
    store: SqliteLibraryStore, library_path: Path, tmp_path: Path, path: tuple[object, ...]
) -> None:
    document = _seed_document()
    _drop_key(document, path)
    with pytest.raises(SeedDataError, match="missing"):
        seed_demo_data(store, _write_seed(tmp_path, document))
    assert count_rows(library_path, "cameras") == 0


def test_a_seed_that_is_not_json_is_refused(store: SqliteLibraryStore, tmp_path: Path) -> None:
    seed_file = tmp_path / "seed.json"
    seed_file.write_text('{"cameras": [', encoding="utf-8")
    with pytest.raises(SeedDataError, match="not valid JSON"):
        seed_demo_data(store, seed_file)
    assert store.list_cameras() == []


def test_a_seed_whose_top_level_is_not_an_object_is_refused(
    store: SqliteLibraryStore, tmp_path: Path
) -> None:
    with pytest.raises(SeedDataError, match="JSON object"):
        seed_demo_data(store, _write_seed(tmp_path, [1, 2, 3]))


def test_a_missing_seed_file_raises_os_error(store: SqliteLibraryStore, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        seed_demo_data(store, tmp_path / "nope.json")


@pytest.mark.parametrize(
    "entry",
    [
        {
            "id": "s-1",
            "clipId": "clip-1029-104215",
            "note": "Hi",
            "savedAt": "2026-10-30T09:12:44Z",
        },
        {"id": "s-1", "clip": {"id": "clip-1029-104215"}, "savedAt": "2026-10-30T10:12:44+01:00"},
    ],
    ids=["clipId", "nested-clip"],
)
def test_a_seed_may_hold_saved_clips(
    store: SqliteLibraryStore, tmp_path: Path, entry: dict[str, object]
) -> None:
    document = copy.deepcopy(_seed_document())
    document["savedClips"] = [entry]

    assert seed_demo_data(store, _write_seed(tmp_path, document)) is True

    [saved] = store.list_saved_clips()
    assert (saved.id, saved.clip.id) == ("s-1", "clip-1029-104215")
    assert saved.saved_at == datetime(2026, 10, 30, 9, 12, 44, tzinfo=UTC)


def test_seed_demo_data_is_importable_from_the_store_module_and_the_package() -> None:
    import askfootage.adapters.sqlite as package
    import askfootage.adapters.sqlite.store as module

    assert package.seed_demo_data is module.seed_demo_data is seed_demo_data
    assert package.SqliteLibraryStore is module.SqliteLibraryStore
