"""GET /api/recordings/{id}/video: the demo clip, with Range support, or a JSON 404."""

from __future__ import annotations

from pathlib import Path

import pytest
from api_fakes import FAKE_MP4, InMemoryLibrary
from api_support import assert_error, build_app
from fastapi.testclient import TestClient

from askfootage.interfaces.api import app as app_module
from askfootage.settings import Settings

VIDEO = "/api/recordings/rec-1029-0600/video"


def test_a_known_recording_streams_the_demo_clip(client: TestClient) -> None:
    response = client.get(VIDEO)
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(FAKE_MP4))
    assert response.content == FAKE_MP4


def test_every_known_recording_plays_the_same_demo_clip(client: TestClient) -> None:
    for recording_id in ("rec-1024-0800", "rec-1030-1200"):
        assert client.get(f"/api/recordings/{recording_id}/video").content == FAKE_MP4


def test_a_range_request_gets_206_with_that_part(client: TestClient) -> None:
    response = client.get(VIDEO, headers={"Range": "bytes=0-7"})
    assert response.status_code == 206
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["content-range"] == f"bytes 0-7/{len(FAKE_MP4)}"
    assert response.content == FAKE_MP4[:8]


def test_a_suffix_range_gets_the_end_of_the_file(client: TestClient) -> None:
    response = client.get(VIDEO, headers={"Range": "bytes=-12"})
    assert response.status_code == 206
    assert response.content == b"end-of-video"


def test_an_open_ended_range_runs_to_the_end(client: TestClient) -> None:
    response = client.get(VIDEO, headers={"Range": "bytes=100-"})
    assert response.status_code == 206
    assert response.content == FAKE_MP4[100:]


@pytest.mark.parametrize(
    "range_header",
    ["bytes=999999-", "bytes=abc", "items=0-5", "bytes=5-2", "bytes=0-1,4-5", "bytes="],
)
def test_a_range_that_cannot_be_served_gets_the_whole_video(
    client: TestClient, range_header: str
) -> None:
    response = client.get(VIDEO, headers={"Range": range_header})
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == FAKE_MP4


def test_an_unknown_recording_is_404(client: TestClient) -> None:
    response = client.get("/api/recordings/rec-nope/video")
    assert assert_error(response, 404, "not_found") == "Recording not found."


@pytest.mark.parametrize("make_it_missing", ["absent", "a folder"])
def test_a_missing_footage_file_is_404(
    store: InMemoryLibrary, fake_settings: Settings, tmp_path: Path, make_it_missing: str
) -> None:
    empty_videos = tmp_path / "no-videos"
    empty_videos.mkdir()
    if make_it_missing == "a folder":
        (empty_videos / "clip1.mp4").mkdir()
    with TestClient(build_app(store, fake_settings, empty_videos)) as client:
        response = client.get(VIDEO)
    assert assert_error(response, 404, "not_found") == "Footage file not attached."
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize("recording_id", ["bad%20id", "rec.1", "x" * 65, "%2E%2E"])
def test_a_bad_recording_id_is_422(client: TestClient, recording_id: str) -> None:
    response = client.get(f"/api/recordings/{recording_id}/video")
    assert assert_error(response, 422, "validation_error").startswith("id:")


@pytest.mark.parametrize(
    "path",
    [
        "/api/recordings/../../contract/openapi.yaml/video",
        "/api/recordings/..%2F..%2Fcontract%2Fopenapi.yaml/video",
        "/api/recordings/rec-1029-0600/video/../../../../conftest.py",
        "/api/recordings/rec-1029-0600/clip1.mp4",
    ],
)
def test_paths_from_the_client_never_reach_the_file_system(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code in (404, 422)
    assert response.headers["content-type"] == "application/json"
    assert set(response.json()) == {"error"}


def test_the_default_videos_folder_is_found_from_the_source_tree() -> None:
    repo_root = Path(app_module.__file__).resolve().parents[3]
    assert app_module.DEFAULT_VIDEOS_DIR == repo_root / "videos"
    assert (repo_root / "contract" / "openapi.yaml").is_file()
    assert app_module.DEMO_SEED_FILE.is_file()
