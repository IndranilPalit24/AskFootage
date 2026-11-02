"""GET /api/recordings/{id}/poster and posterUrl on Recording and Clip.

The renderer is a fake that writes a few bytes, so no ffmpeg, no footage and no network are
needed. The ffmpeg renderer is checked with a fake command runner.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from api_fakes import InMemoryLibrary
from api_support import FAKE_KEY, assert_error, build_app
from fastapi.testclient import TestClient

from askfootage.application.posters import PosterStore
from askfootage.interfaces.api.poster_renderer import FfmpegPosterRenderer
from askfootage.settings import Settings

JPEG = b"\xff\xd8fake-poster\xff\xd9"
REC = "rec-1029-0600"  # lengthSeconds 1860 in the demo dataset
POSTER = f"/api/recordings/{REC}/poster"
CLIP = "clip-1029-104215"  # recording rec-1029-1030, startSeconds 735
SECRET_PATH = "C:\\secret\\ffmpeg.exe"


class FakeRenderer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[Path, int]] = []

    def render(self, video: Path, at_seconds: int, destination: Path) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append((video, at_seconds))
        destination.write_bytes(JPEG)


@pytest.fixture
def renderer() -> FakeRenderer:
    return FakeRenderer()


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "posters-cache"


@pytest.fixture
def client(
    store: InMemoryLibrary,
    fake_settings: Settings,
    videos_dir: Path,
    renderer: FakeRenderer,
    cache_dir: Path,
) -> Iterator[TestClient]:
    app = build_app(store, fake_settings, videos_dir, posters=PosterStore(cache_dir, renderer))
    with TestClient(app) as test_client:
        yield test_client


def _client_with(
    store: InMemoryLibrary, settings: Settings, videos: Path, posters: PosterStore
) -> TestClient:
    return TestClient(build_app(store, settings, videos, posters=posters))


# --- The route --------------------------------------------------------------------------------


def test_a_poster_is_a_jpeg_from_the_middle_by_default(
    client: TestClient, renderer: FakeRenderer, videos_dir: Path
) -> None:
    response = client.get(POSTER)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == JPEG
    assert renderer.calls == [(videos_dir / "clip1.mp4", 930)]


def test_t_picks_the_second_and_is_rounded_down(client: TestClient, renderer: FakeRenderer) -> None:
    assert client.get(POSTER, params={"t": "12.9"}).status_code == 200
    assert [second for _, second in renderer.calls] == [12]


def test_t_past_the_end_is_kept_inside_the_recording(
    client: TestClient, renderer: FakeRenderer
) -> None:
    assert client.get(POSTER, params={"t": "5000"}).status_code == 200
    assert [second for _, second in renderer.calls] == [1859]


def test_the_poster_is_cached_as_id_dash_second(
    client: TestClient, renderer: FakeRenderer, cache_dir: Path
) -> None:
    client.get(POSTER, params={"t": 7})
    assert [path.name for path in cache_dir.iterdir()] == [f"{REC}-7.jpg"]
    again = client.get(POSTER, params={"t": 7})
    assert again.content == JPEG
    assert len(renderer.calls) == 1  # the second request was a cache hit
    client.get(POSTER, params={"t": 8})
    assert len(renderer.calls) == 2


def test_a_failed_render_leaves_nothing_in_the_cache(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path, cache_dir: Path
) -> None:
    posters = PosterStore(cache_dir, FakeRenderer(OSError("boom")))
    with _client_with(store, fake_settings, videos_dir, posters) as client:
        assert client.get(POSTER).status_code == 404
    assert not any(cache_dir.iterdir())


@pytest.mark.parametrize("value", ["-1", "86401", "abc", "nan", "inf", ""])
def test_a_bad_t_is_a_validation_error(client: TestClient, value: str) -> None:
    assert_error(client.get(POSTER, params={"t": value}), 422, "validation_error")


@pytest.mark.parametrize("bad_id", ["rec.1", "a" * 65, "rec%20x"])
def test_a_bad_id_is_a_validation_error(client: TestClient, bad_id: str) -> None:
    assert_error(client.get(f"/api/recordings/{bad_id}/poster"), 422, "validation_error")


def test_an_unknown_recording_is_404(client: TestClient) -> None:
    response = client.get("/api/recordings/rec-nope/poster")
    assert assert_error(response, 404, "not_found") == "Recording not found."


def test_a_recording_without_footage_is_404(
    store: InMemoryLibrary, fake_settings: Settings, tmp_path: Path, cache_dir: Path
) -> None:
    empty = tmp_path / "empty-videos"
    empty.mkdir()
    posters = PosterStore(cache_dir, FakeRenderer())
    with _client_with(store, fake_settings, empty, posters) as client:
        response = client.get(POSTER)
    assert assert_error(response, 404, "not_found") == "Footage file not attached."


@pytest.mark.parametrize("error", [OSError(f"failed at {SECRET_PATH}"), ValueError("x")])
def test_a_render_failure_is_a_plain_404_that_leaks_nothing(
    store: InMemoryLibrary,
    fake_settings: Settings,
    videos_dir: Path,
    cache_dir: Path,
    error: Exception,
) -> None:
    posters = PosterStore(cache_dir, FakeRenderer(error))
    with _client_with(store, fake_settings, videos_dir, posters) as client:
        response = client.get(POSTER)
    assert assert_error(response, 404, "not_found") == "Poster not available."
    for hidden in (str(videos_dir), str(cache_dir), "secret", "Traceback", FAKE_KEY):
        assert hidden not in response.text


def test_an_app_without_a_poster_store_answers_404_and_null_urls(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    app = build_app(store, fake_settings, videos_dir)
    app.state.context = replace(app.state.context, posters=None)
    with TestClient(app) as client:
        assert_error(client.get(POSTER), 404, "not_found")
        listed = client.get("/api/recordings", params={"day": "2026-10-29"}).json()
        assert listed
        assert all(recording["posterUrl"] is None for recording in listed)
        assert client.get(f"/api/clips/{CLIP}").json()["posterUrl"] is None


# --- The store --------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../x", "a/b", "a\\b", "", "a.b", "x" * 65])
def test_the_store_refuses_an_unsafe_id(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        PosterStore(tmp_path, FakeRenderer()).path_for(bad, 1)


@pytest.mark.parametrize("bad", [-1, 86401, 1.5, True])
def test_the_store_refuses_an_unsafe_second(tmp_path: Path, bad: object) -> None:
    with pytest.raises(ValueError):
        PosterStore(tmp_path, FakeRenderer()).path_for("rec-1", bad)  # type: ignore[arg-type]


def test_the_store_path_stays_inside_the_directory(tmp_path: Path) -> None:
    path = PosterStore(tmp_path, FakeRenderer()).path_for("rec-1", 3)
    assert path == tmp_path / "rec-1-3.jpg"


# --- posterUrl --------------------------------------------------------------------------------


def test_every_recording_points_at_its_poster(client: TestClient) -> None:
    listed = client.get("/api/recordings", params={"day": "2026-10-29"}).json()
    assert listed
    for recording in listed:
        assert recording["posterUrl"] == f"/api/recordings/{recording['id']}/poster"


def test_a_clip_points_at_the_poster_of_its_first_matched_second(client: TestClient) -> None:
    clip = client.get(f"/api/clips/{CLIP}").json()
    assert clip["posterUrl"] == "/api/recordings/rec-1029-1030/poster?t=735"
    assert client.get(clip["posterUrl"]).status_code == 200


def test_search_and_saved_clips_carry_the_poster_url(client: TestClient) -> None:
    found = client.post(
        "/api/search", json={"question": "a person with a box", "day": "2026-10-29"}
    ).json()
    assert found["clips"]
    for clip in found["clips"]:
        assert clip["posterUrl"] == (
            f"/api/recordings/{clip['recordingId']}/poster?t={clip['startSeconds']}"
        )
    saved = client.post("/api/saved-clips", json={"clipId": CLIP}).json()
    assert saved["clip"]["posterUrl"].endswith("/poster?t=735")


def test_posterurl_is_null_when_there_is_no_footage(
    store: InMemoryLibrary, fake_settings: Settings, tmp_path: Path, cache_dir: Path
) -> None:
    empty = tmp_path / "empty-videos"
    empty.mkdir()
    posters = PosterStore(cache_dir, FakeRenderer())
    with _client_with(store, fake_settings, empty, posters) as client:
        listed = client.get("/api/recordings", params={"day": "2026-10-29"}).json()
        assert all(recording["posterUrl"] is None for recording in listed)
        assert client.get(f"/api/clips/{CLIP}").json()["posterUrl"] is None


def test_the_app_documents_the_poster_route(client: TestClient) -> None:
    spec = client.get("/api/openapi.json").json()
    operation = spec["paths"]["/api/recordings/{id}/poster"]["get"]
    assert operation["operationId"] == "getRecordingPoster"
    assert set(operation["responses"]) == {"200", "404", "422", "500"}
    assert "image/jpeg" in operation["responses"]["200"]["content"]


# --- The ffmpeg renderer ----------------------------------------------------------------------


class Result:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode


class Runner:
    def __init__(
        self, returncode: int = 0, *, write: bool = True, error: Exception | None = None
    ) -> None:
        self.returncode, self.write, self.error = returncode, write, error
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, args: list[str], *, timeout: float) -> Result:
        self.calls.append((args, timeout))
        if self.error is not None:
            raise self.error
        if self.write:
            Path(args[-1]).write_bytes(JPEG)
        return Result(self.returncode)


def _renderer(runner: Runner, which: str | None = "/bin/ffmpeg") -> FfmpegPosterRenderer:
    return FfmpegPosterRenderer(runner=runner, which=lambda name: which)


def test_ffmpeg_is_run_with_an_argument_list_and_the_local_file_protocol(tmp_path: Path) -> None:
    runner = Runner()
    video, out = tmp_path / "v.mp4", tmp_path / "out.jpg"
    _renderer(runner).render(video, 42, out)
    assert len(runner.calls) == 1
    args, timeout = runner.calls[0]
    assert isinstance(args, list) and timeout > 0
    assert args[0] == "/bin/ffmpeg"
    assert args[args.index("-protocol_whitelist") + 1] == "file"
    assert args[args.index("-ss") + 1] == "42"
    assert args[args.index("-i") + 1] == str(video)
    assert "scale=640:-2" in args
    assert args[args.index("-frames:v") + 1] == "1"
    assert args[-1] == str(out)
    assert out.read_bytes() == JPEG


def test_a_missing_ffmpeg_is_an_oserror_that_names_no_path(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="not found") as raised:
        _renderer(Runner(), which=None).render(tmp_path / "v.mp4", 1, tmp_path / "o.jpg")
    assert str(tmp_path) not in str(raised.value)


@pytest.mark.parametrize(
    "runner",
    [
        Runner(returncode=1),
        Runner(write=False),
        Runner(error=OSError(SECRET_PATH)),
        Runner(error=subprocess.TimeoutExpired("ffmpeg", 1)),
    ],
    ids=["exit code", "no output", "cannot start", "timeout"],
)
def test_ffmpeg_failures_are_oserrors_without_details(tmp_path: Path, runner: Runner) -> None:
    with pytest.raises(OSError) as raised:
        _renderer(runner).render(tmp_path / "v.mp4", 1, tmp_path / "o.jpg")
    assert "secret" not in str(raised.value) and str(tmp_path) not in str(raised.value)


def test_a_missing_ffmpeg_through_the_route_is_a_plain_404(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path, cache_dir: Path
) -> None:
    posters = PosterStore(cache_dir, _renderer(Runner(), which=None))
    with _client_with(store, fake_settings, videos_dir, posters) as client:
        response = client.get(POSTER)
    assert assert_error(response, 404, "not_found") == "Poster not available."
