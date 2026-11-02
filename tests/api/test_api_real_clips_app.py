"""The launcher for the real clips: its own footage per recording, no key, no network."""

from datetime import date, time
from pathlib import Path

from fastapi.testclient import TestClient

from askfootage.interfaces.real_clips import PerRecordingFootage, create_app
from askfootage.ports.library_store import Recording


def recording(recording_id: str) -> Recording:
    return Recording(recording_id, "CAM-001", date(2026, 10, 30), time(9, 0), 10, "ready")


def test_each_recording_plays_its_own_file(tmp_path: Path) -> None:
    (tmp_path / "clip2.mp4").write_bytes(b"v")
    footage = PerRecordingFootage(tmp_path)
    assert footage.footage_for(recording("clip2")) == tmp_path / "clip2.mp4"
    assert footage.footage_for(recording("clip1")) is None


def test_an_app_over_an_empty_data_folder_answers(tmp_path: Path) -> None:
    app = create_app(tmp_path / "real", tmp_path / "videos")
    with TestClient(app) as client:
        assert client.get("/api/cameras").json() == []
        assert client.get("/api/status").status_code == 200
