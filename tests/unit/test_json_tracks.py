"""The JSON track store used by the command-line tools."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app_fakes import track

from askfootage.adapters.storage.json_tracks import JsonTrackStore
from askfootage.adapters.storage.local_files import LocalVideoFiles
from askfootage.ports.track_store import TrackDataError


def test_round_trip_replace_and_delete(tmp_path: Path) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    first = [track(2, "person", range(0, 5)), track(1, "person", range(3, 9))]
    store.save_tracks("v", "person", first)
    got = store.tracks_for("v", "person")
    assert [t.track_id for t in got] == [1, 2]
    assert got[1] == first[0]
    store.save_tracks("v", "person", [track(5, "person", [0])])
    assert [t.track_id for t in store.tracks_for("v", "person")] == [5]
    assert store.tracks_for("v", "other") == [] and store.tracks_for("nope", "person") == []
    assert store.delete_video("v") == 1
    assert store.tracks_for("v", "person") == []


def test_refuses_wrong_label_and_repeated_ids(tmp_path: Path) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    with pytest.raises(ValueError):
        store.save_tracks("v", "person", [track(1, "box", [0])])
    with pytest.raises(ValueError):
        store.save_tracks("v", "person", [track(1, "person", [0]), track(1, "person", [5])])
    assert store.tracks_for("v", "person") == []


# --- hardening ---------------------------------------------------------------------------


def _file(tmp_path: Path, video: str = "v") -> Path:
    return tmp_path / video / "tracks.json"


def test_frame_size_round_trip_and_validation(tmp_path: Path) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    assert store.frame_size("v") is None
    store.save_tracks("v", "person", [track(1, "person", [0])])
    store.save_frame_size("v", 640, 360)
    assert store.frame_size("v") == (640, 360)
    assert len(store.tracks_for("v", "person")) == 1  # same file, tracks untouched
    store.save_tracks("v", "person", [])
    assert store.frame_size("v") == (640, 360)  # replacing tracks keeps the size
    for bad in ((0, 10), (10, -1), (True, 5), (1.5, 2)):
        with pytest.raises(ValueError):
            store.save_frame_size("v", *bad)
    assert store.frame_size("v") == (640, 360)


def test_frame_size_alone_creates_the_file(tmp_path: Path) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    store.save_frame_size("w", 10, 20)
    assert store.frame_size("w") == (10, 20) and store.tracks_for("w", "person") == []


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[1, 2]",
        '{"version": 2, "concepts": []}',
        '{"version": 2, "concepts": {"person": {"tracks": [{"track_id": 1}]}}}',
        '{"version": 2, "concepts": {"person": {"tracks": [{"track_id": 1, "points": [[0, 1]]}]}}}',
        '{"version": 2, "concepts": {"person": {"tracks": [{"track_id": "x", "points": []}]}}}',
        '{"version": 2, "meta": {"frame_size": "big"}, "concepts": {}}',
    ],
)
def test_corrupt_file_raises_a_typed_error_without_path(tmp_path: Path, text: str) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    store.save_tracks("v", "other", [])
    _file(tmp_path).write_text(text, encoding="utf-8")
    with pytest.raises(TrackDataError) as caught:
        store.tracks_for("v", "person")
        store.frame_size("v")
    assert str(tmp_path) not in str(caught.value)


def test_corrupt_file_can_still_be_deleted(tmp_path: Path) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    store.save_frame_size("v", 1, 1)
    _file(tmp_path).write_text("garbage", encoding="utf-8")
    assert store.delete_video("v") == 0 and not _file(tmp_path).exists()


def test_reading_an_unknown_video_creates_no_folder(tmp_path: Path) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    assert store.tracks_for("ghost", "person") == []
    assert store.frame_size("ghost") is None
    assert store.concept_done("ghost", "person") is False
    assert store.delete_video("ghost") == 0
    assert list(tmp_path.iterdir()) == []


def test_ran_empty_marker(tmp_path: Path) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    assert store.concept_done("v", "forklift") is False
    store.save_tracks("v", "forklift", [])
    assert store.concept_done("v", "forklift") is True
    assert store.tracks_for("v", "forklift") == []
    assert store.concept_done("v", "person") is False


def test_legacy_flat_file_is_still_read(tmp_path: Path) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    store.save_frame_size("v", 1, 1)
    _file(tmp_path).write_text(
        '{"person": [{"track_id": 3, "points": [[0, 1, 2, 3, 4]]}]}', encoding="utf-8"
    )
    assert [t.track_id for t in store.tracks_for("v", "person")] == [3]
    assert store.concept_done("v", "person") is True


def test_concurrent_saves_to_one_video_lose_nothing_and_leave_no_temp_files(
    tmp_path: Path,
) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    labels = [f"c{i}" for i in range(12)]

    def save(label: str) -> None:
        store.save_tracks("v", label, [track(1, label, [0, 1])])

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(save, labels))
    assert all(len(store.tracks_for("v", c)) == 1 for c in labels)
    assert [p.name for p in (tmp_path / "v").iterdir()] == ["tracks.json"]


def test_failed_write_keeps_the_old_file_and_cleans_up(tmp_path: Path, monkeypatch) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    store.save_tracks("v", "person", [track(1, "person", [0])])

    def boom(*_args):
        raise OSError("disk full")

    monkeypatch.setattr("askfootage.adapters.storage.json_tracks.os.replace", boom)
    with pytest.raises(OSError):
        store.save_tracks("v", "person", [track(9, "person", [0])])
    monkeypatch.undo()
    assert [t.track_id for t in store.tracks_for("v", "person")] == [1]
    assert [p.name for p in (tmp_path / "v").iterdir()] == ["tracks.json"]


def test_data_is_fsynced_before_replace(tmp_path: Path, monkeypatch) -> None:
    import os

    calls: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(
        os, "replace", lambda a, b: (calls.append("replace"), real_replace(a, b))[1]
    )
    JsonTrackStore(LocalVideoFiles(tmp_path)).save_frame_size("v", 3, 3)
    assert calls == ["fsync", "replace"]


def test_prepared_info_round_trip(tmp_path: Path) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    assert store.prepared_info("v") is None
    store.save_prepared_info("v", frame_count=300, source_fingerprint="abc")
    assert store.prepared_info("v") == (300, "abc")


def test_saving_over_a_corrupt_file_starts_it_afresh(tmp_path: Path) -> None:
    store = JsonTrackStore(LocalVideoFiles(tmp_path))
    store.save_frame_size("v", 1, 1)
    _file(tmp_path).write_text("garbage", encoding="utf-8")
    store.save_tracks("v", "person", [track(1, "person", [0])])
    assert len(store.tracks_for("v", "person")) == 1
