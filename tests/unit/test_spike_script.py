"""Behaviour of scripts/api_spike.py, the API spike, tested fully offline.

Every test hands main() a Settings built directly with the fake key "test-key-not-real",
a data directory under tmp_path, and an offline transport: either a FakeTransport that
answers by path, or a MetaHttpClient wired to httpx.MockTransport. Nothing reaches the
network and nothing reads the real settings.
"""

import base64
import importlib.util
import io
import json
import subprocess
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from askfootage.adapters.meta.client import MetaHttpClient
from askfootage.adapters.meta.transport import (
    MetaApiError,
    MetaConnectionError,
    MetaRequest,
    RawResponse,
)
from askfootage.settings import ConfigurationError, Settings

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "api_spike.py"
FAKE_KEY = "test-key-not-real"
BASE_URL = "https://api.example.test/v1"
VIDEO_BYTES = b"fake video bytes"
FILE_REPLY = '{"id": "file-abc123", "object": "file"}'
SAM_REPLY = 'event: delta\ndata: {"frame": 0}\n\nevent: delta\ndata: {"frame": 1}\n\n'
ENV_NAMES = ("META_API_KEY", "META_API_BASE_URL", "MAX_RUN_COST_USD", "DATA_DIR", "ASKFOOTAGE_DEMO")


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("api_spike_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


spike = _load_script()


class FakeTransport:
    """Answers each request by its path from a table, and keeps every request it gets."""

    def __init__(self, replies: dict[str, RawResponse | Exception] | None = None) -> None:
        self.replies = replies if replies is not None else {}
        self.requests: list[MetaRequest] = []

    def send(self, request: MetaRequest) -> RawResponse:
        self.requests.append(request)
        reply = self.replies[request.path]
        if isinstance(reply, Exception):
            raise reply
        return reply


def _ok_transport() -> FakeTransport:
    return FakeTransport(
        {
            "/files": RawResponse(200, FILE_REPLY),
            "/responses": RawResponse(200, SAM_REPLY),
        }
    )


def _mock_client(settings: Settings, handler: Callable[[httpx.Request], httpx.Response]):
    """A real MetaHttpClient whose HTTP goes to `handler`, with waits that do not wait."""
    calls: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(record))
    return MetaHttpClient(settings, http=http, sleep=lambda _seconds: None), calls


def _settings(tmp_path: Path, *, key: str | None = FAKE_KEY, cap: str = "25") -> Settings:
    values: dict[str, Any] = {
        "META_API_BASE_URL": BASE_URL,
        "MAX_RUN_COST_USD": cap,
        "DATA_DIR": str(tmp_path / "data"),
        "ASKFOOTAGE_DEMO": False,
    }
    if key is not None:
        values["META_API_KEY"] = key
    return Settings(_env_file=None, **values)


@pytest.fixture(autouse=True)
def _no_askfootage_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return _settings(tmp_path)


@pytest.fixture
def video(tmp_path: Path) -> Path:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(VIDEO_BYTES)
    return clip


def run(argv: list[str], settings: Settings, transport: Any = None) -> tuple[int, str]:
    """Run main() and return its exit code and everything it printed."""
    out = io.StringIO()
    code = spike.main(argv, settings=settings, transport=transport, out=out)
    return code, out.getvalue()


def sam_args(video: Path, *extra: str, duration: str = "10") -> list[str]:
    return ["sam", "--video", str(video), "--object", "car", "--duration-seconds", duration, *extra]


# --- Dry runs ---------------------------------------------------------------------------------


def test_check_key_dry_run_sends_nothing_and_shows_the_request(settings: Settings) -> None:
    transport = FakeTransport()
    code, output = run(["check-key"], settings, transport)
    assert code == 0
    assert transport.requests == []
    assert "POST" in output
    assert "/responses" in output
    assert "muse-spark-1.3" in output
    assert "Reply with the single word OK." in output
    assert "nothing was sent" in output.lower()
    assert "--yes" in output


@pytest.mark.parametrize("extra", [(), ("--inline",), ("--no-stream",)])
def test_sam_dry_run_sends_nothing(settings: Settings, video: Path, extra: tuple[str, ...]) -> None:
    transport = _ok_transport()
    code, output = run(sam_args(video, *extra), settings, transport)
    assert code == 0
    assert transport.requests == []
    assert "nothing was sent" in output.lower()
    assert "sam-3.1" in output
    assert "/responses" in output


def test_sam_dry_run_writes_no_recording(settings: Settings, video: Path) -> None:
    run(sam_args(video), settings, _ok_transport())
    assert not (settings.data_dir / "recordings").exists()


def test_a_dry_run_works_without_a_key(tmp_path: Path, video: Path) -> None:
    keyless = _settings(tmp_path, key=None)
    assert run(["check-key"], keyless, FakeTransport())[0] == 0
    assert run(sam_args(video), keyless, _ok_transport())[0] == 0


def test_settings_come_from_load_settings_when_not_given(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    calls: list[str] = []

    def fake_load_settings() -> Settings:
        calls.append("loaded")
        return settings

    monkeypatch.setattr(spike, "load_settings", fake_load_settings)
    out = io.StringIO()
    assert spike.main(["check-key"], transport=FakeTransport(), out=out) == 0
    assert calls == ["loaded"]


def test_invalid_settings_exit_2(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Settings:
        raise ConfigurationError("MAX_RUN_COST_USD: must be greater than 0")

    monkeypatch.setattr(spike, "load_settings", broken)
    out = io.StringIO()
    transport = FakeTransport()
    assert spike.main(["check-key", "--yes"], transport=transport, out=out) == 2
    assert "MAX_RUN_COST_USD" in out.getvalue()
    assert transport.requests == []


# --- check-key with --yes ---------------------------------------------------------------------


def test_check_key_with_yes_sends_exactly_the_documented_body(settings: Settings) -> None:
    transport = FakeTransport({"/responses": RawResponse(200, '{"output_text": "OK"}')})
    code, _ = run(["check-key", "--yes"], settings, transport)
    assert code == 0
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.path == "/responses"
    assert request.upload is None
    assert dict(request.json_body or {}) == {
        "model": "muse-spark-1.3",
        "input": "Reply with the single word OK.",
        "max_output_tokens": 16,
    }


def test_check_key_pass_prints_status_length_and_the_start_of_the_reply(
    settings: Settings,
) -> None:
    body = '{"output_text": "OK"}' + "z" * 400
    transport = FakeTransport({"/responses": RawResponse(200, body)})
    code, output = run(["check-key", "--yes"], settings, transport)
    assert code == 0
    assert "PASS" in output
    assert "200" in output
    assert str(len(body)) in output
    assert body[:200] in output
    assert body[:201] not in output


def test_check_key_goes_through_the_real_client_to_the_base_url(settings: Settings) -> None:
    client, calls = _mock_client(settings, lambda _r: httpx.Response(200, text='{"ok": 1}'))
    code, output = run(["check-key", "--yes"], settings, client)
    assert code == 0
    assert "PASS" in output
    assert len(calls) == 1
    assert str(calls[0].url) == f"{BASE_URL}/responses"


HINTS = {
    400: "body not accepted",
    401: "key rejected",
    403: "not allowed or billing",
    404: "model or path",
    429: "rate limited",
}


@pytest.mark.parametrize(("status", "hint"), sorted(HINTS.items()))
def test_each_error_status_gives_its_hint(settings: Settings, status: int, hint: str) -> None:
    client, _ = _mock_client(settings, lambda _r: httpx.Response(status, text="nope"))
    code, output = run(["check-key", "--yes"], settings, client)
    assert code == 1
    assert "FAIL" in output
    assert str(status) in output
    assert hint in output.lower()
    for other in HINTS.values():
        if other != hint:
            assert other not in output.lower()


def test_a_connection_error_hints_at_network_or_proxy(settings: Settings) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    client, _ = _mock_client(settings, refuse)
    code, output = run(["check-key", "--yes"], settings, client)
    assert code == 1
    assert "FAIL" in output
    assert "network or proxy" in output.lower()


def test_a_missing_key_with_yes_exits_2_and_sends_nothing(tmp_path: Path) -> None:
    keyless = _settings(tmp_path, key=None)
    client, calls = _mock_client(keyless, lambda _r: httpx.Response(200))
    code, output = run(["check-key", "--yes"], keyless, client)
    assert code == 2
    assert calls == []
    assert "META_API_KEY" in output


# --- The key, headers and the environment never reach the output -----------------------------

ECHO = f'{{"error": "bad token Bearer {FAKE_KEY}", "authorization": "Bearer {FAKE_KEY}"}}'


def _echo_cases(video: Path, settings: Settings) -> list[tuple[list[str], Any]]:
    client_401, _ = _mock_client(settings, lambda _r: httpx.Response(401, text=ECHO))
    return [
        (["check-key"], FakeTransport()),
        (sam_args(video), _ok_transport()),
        (["check-key", "--yes"], FakeTransport({"/responses": RawResponse(200, ECHO)})),
        (["check-key", "--yes"], client_401),
        (["check-key", "--yes"], FakeTransport({"/responses": MetaApiError(403, ECHO)})),
        (["check-key", "--yes"], FakeTransport({"/responses": MetaConnectionError(ECHO)})),
        (
            sam_args(video, "--yes"),
            FakeTransport(
                {"/files": RawResponse(200, FILE_REPLY), "/responses": RawResponse(200, ECHO)}
            ),
        ),
        (sam_args(video, "--yes"), FakeTransport({"/files": RawResponse(200, ECHO)})),
        (
            sam_args(video, "--yes", "--inline"),
            FakeTransport({"/responses": RawResponse(200, ECHO)}),
        ),
    ]


@pytest.mark.parametrize("case", range(9))
def test_the_key_never_appears_in_the_output(
    settings: Settings, video: Path, case: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASKFOOTAGE_SPIKE_SENTINEL", "sentinel-environment-value")
    argv, transport = _echo_cases(video, settings)[case]
    _, output = run(argv, settings, transport)
    assert output  # something was printed, so the checks below are not vacuous
    assert FAKE_KEY not in output
    assert "sentinel-environment-value" not in output


def test_no_header_is_printed_on_a_live_run(settings: Settings, video: Path) -> None:
    client, _ = _mock_client(settings, lambda _r: httpx.Response(200, text="OK"))
    for argv in (["check-key", "--yes"], sam_args(video, "--yes", "--inline")):
        _, output = run(argv, settings, client)
        lowered = output.lower()
        assert "authorization" not in lowered
        assert "bearer" not in lowered
        assert "content-type" not in lowered


# --- Cost -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "fps", "cost"),
    [
        ("30", "30", "0.18"),  # 900 frames
        ("3", "5", "0.01"),  # 15 frames, billed as the 50-frame minimum
        ("10.01", "30", "0.0602"),  # 300.3 frames round up to 301
        ("1", "50", "0.01"),  # exactly the minimum
    ],
)
def test_cost_estimate(seconds: str, fps: str, cost: str) -> None:
    estimate = spike.estimate_cost_usd(Decimal(seconds), Decimal(fps))
    assert isinstance(estimate, Decimal)
    assert estimate == Decimal(cost)


def test_the_dry_run_shows_the_estimated_cost(settings: Settings, video: Path) -> None:
    _, output = run(sam_args(video, duration="30"), settings, _ok_transport())
    assert "0.18" in output


def test_fps_defaults_to_30(settings: Settings, video: Path) -> None:
    # 30 s at the default 30 fps costs 0.18, just over a 0.17 limit.
    code, _ = run(sam_args(video, "--max-cost-usd", "0.17", duration="30"), settings, None)
    assert code == 2


@pytest.mark.parametrize("yes", [(), ("--yes",)])
def test_a_cost_above_max_cost_usd_is_refused(
    settings: Settings, video: Path, yes: tuple[str, ...]
) -> None:
    transport = _ok_transport()
    argv = sam_args(video, "--fps", "30", "--max-cost-usd", "0.17", *yes, duration="30")
    code, output = run(argv, settings, transport)
    assert code == 2
    assert transport.requests == []
    assert "0.18" in output
    assert "refused" in output.lower()


def test_the_default_max_cost_is_fifty_cents(settings: Settings, video: Path) -> None:
    transport = _ok_transport()
    # 0.50 is 2500 frames; 84 s at 30 fps is 2520 frames.
    assert run(sam_args(video, "--yes", duration="84"), settings, transport)[0] == 2
    assert run(sam_args(video, "--yes", duration="83"), settings, transport)[0] == 0
    assert len(transport.requests) == 2


def test_a_cost_above_the_settings_cap_is_refused(tmp_path: Path, video: Path) -> None:
    capped = _settings(tmp_path, cap="0.10")
    transport = _ok_transport()
    argv = sam_args(video, "--max-cost-usd", "5", "--yes", duration="30")
    code, output = run(argv, capped, transport)
    assert code == 2
    assert transport.requests == []
    assert "MAX_RUN_COST_USD" in output


def test_a_cost_equal_to_the_limit_is_allowed(settings: Settings, video: Path) -> None:
    transport = _ok_transport()
    argv = sam_args(video, "--max-cost-usd", "0.18", "--yes", duration="30")
    assert run(argv, settings, transport)[0] == 0
    assert len(transport.requests) == 2


# --- sam with --yes ---------------------------------------------------------------------------


def test_sam_uploads_then_asks_with_the_file_id(settings: Settings, video: Path) -> None:
    transport = _ok_transport()
    code, _ = run(sam_args(video, "--yes"), settings, transport)
    assert code == 0
    upload, ask = transport.requests
    assert upload.path == "/files"
    assert upload.upload is not None
    assert upload.upload.path == video
    assert upload.upload.purpose == "user_data"
    assert ask.path == "/responses"
    assert dict(ask.json_body or {}) == {
        "model": "sam-3.1",
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "car"},
                    {"type": "input_video", "file_id": "file-abc123"},
                ],
            }
        ],
        "stream": True,
        "metadata": {"include_confidence": "true"},
    }


def test_the_object_noun_is_trimmed(settings: Settings, video: Path) -> None:
    transport = _ok_transport()
    argv = ["sam", "--video", str(video), "--object", "  red car  ", "--duration-seconds", "5"]
    assert run([*argv, "--yes"], settings, transport)[0] == 0
    content = transport.requests[1].json_body["input"][0]["content"]  # type: ignore[index]
    assert content[0] == {"type": "input_text", "text": "red car"}


@pytest.mark.parametrize(("suffix", "mime"), [(".mp4", "video/mp4"), (".MOV", "video/quicktime")])
def test_inline_sends_a_base64_data_url_and_no_upload(
    settings: Settings, tmp_path: Path, suffix: str, mime: str
) -> None:
    clip = tmp_path / f"clip{suffix}"
    clip.write_bytes(VIDEO_BYTES)
    transport = _ok_transport()
    code, _ = run(sam_args(clip, "--yes", "--inline"), settings, transport)
    assert code == 0
    assert [request.path for request in transport.requests] == ["/responses"]
    part = transport.requests[0].json_body["input"][0]["content"][1]  # type: ignore[index]
    assert set(part) == {"type", "video_url"}
    assert part["type"] == "input_video"
    prefix = f"data:{mime};base64,"
    assert part["video_url"].startswith(prefix)
    assert base64.b64decode(part["video_url"][len(prefix) :]) == VIDEO_BYTES


def test_no_stream_sends_stream_false(settings: Settings, video: Path) -> None:
    transport = _ok_transport()
    run(sam_args(video, "--yes", "--no-stream"), settings, transport)
    assert transport.requests[1].json_body["stream"] is False  # type: ignore[index]


def test_sam_prints_status_length_lines_excerpt_and_recording_path(
    settings: Settings, video: Path
) -> None:
    body = SAM_REPLY + "x" * 400
    transport = FakeTransport(
        {"/files": RawResponse(200, FILE_REPLY), "/responses": RawResponse(200, body)}
    )
    code, output = run(sam_args(video, "--yes"), settings, transport)
    assert code == 0
    assert "200" in output
    assert str(len(body)) in output
    assert f"lines: {len(body.splitlines())}" in output.lower()
    assert body[:300] in output
    assert body[:301] not in output
    recordings = list((settings.data_dir / "recordings").glob("*.json"))
    assert len(recordings) == 2  # the upload and the answer
    assert any(str(path) in output for path in recordings)
    answer = [p for p in recordings if json.loads(p.read_text("utf-8"))["path"] == "/responses"]
    assert str(answer[0]) in output


def test_sam_does_not_parse_the_reply(settings: Settings, video: Path) -> None:
    # Whatever comes back is shown raw; a reply that is not JSON or SSE is still a success.
    transport = FakeTransport(
        {"/files": RawResponse(200, FILE_REPLY), "/responses": RawResponse(200, "<<not json>>")}
    )
    code, output = run(sam_args(video, "--yes"), settings, transport)
    assert code == 0
    assert "<<not json>>" in output


def test_a_repeat_run_is_served_from_the_recording(settings: Settings, video: Path) -> None:
    transport = FakeTransport({"/responses": RawResponse(200, SAM_REPLY)})
    first = run(sam_args(video, "--yes", "--inline"), settings, transport)
    second = run(sam_args(video, "--yes", "--inline"), settings, transport)
    assert first[0] == second[0] == 0
    assert len(transport.requests) == 1  # one live request across both runs
    assert "recording" in second[1].lower()
    assert SAM_REPLY[:50] in second[1]


def test_a_repeat_upload_run_sends_nothing_new(settings: Settings, video: Path) -> None:
    transport = _ok_transport()
    run(sam_args(video, "--yes"), settings, transport)
    run(sam_args(video, "--yes"), settings, transport)
    assert [request.path for request in transport.requests] == ["/files", "/responses"]


def test_check_key_is_never_recorded(settings: Settings) -> None:
    # A recorded check would replay a PASS for a key that has since stopped working.
    transport = FakeTransport({"/responses": RawResponse(200, "OK")})
    run(["check-key", "--yes"], settings, transport)
    run(["check-key", "--yes"], settings, transport)
    assert len(transport.requests) == 2
    assert not (settings.data_dir / "recordings").exists()


@pytest.mark.parametrize(("status", "hint"), [(401, "key rejected"), (429, "rate limited")])
def test_a_sam_api_failure_exits_1_with_its_hint(
    settings: Settings, video: Path, status: int, hint: str
) -> None:
    transport = FakeTransport(
        {"/files": RawResponse(200, FILE_REPLY), "/responses": MetaApiError(status, "nope")}
    )
    code, output = run(sam_args(video, "--yes"), settings, transport)
    assert code == 1
    assert "FAIL" in output
    assert hint in output.lower()


def test_a_sam_connection_failure_exits_1(settings: Settings, video: Path) -> None:
    transport = FakeTransport({"/files": MetaConnectionError("could not connect")})
    code, output = run(sam_args(video, "--yes"), settings, transport)
    assert code == 1
    assert "network or proxy" in output.lower()


@pytest.mark.parametrize("reply", ["not json", '{"object": "file"}', '{"id": ""}', "[1, 2]"])
def test_an_upload_reply_without_a_file_id_exits_1(
    settings: Settings, video: Path, reply: str
) -> None:
    transport = FakeTransport({"/files": RawResponse(200, reply)})
    code, output = run(sam_args(video, "--yes"), settings, transport)
    assert code == 1
    assert "file id" in output.lower()
    assert [request.path for request in transport.requests] == ["/files"]


# --- Validation -------------------------------------------------------------------------------


def _bad_argvs(tmp_path: Path, video: Path) -> dict[str, list[str]]:
    avi = tmp_path / "clip.avi"
    avi.write_bytes(VIDEO_BYTES)
    folder = tmp_path / "folder.mp4"
    folder.mkdir()
    base = ["sam", "--duration-seconds", "10", "--yes"]
    return {
        "missing-file": [*base, "--video", str(tmp_path / "nope.mp4"), "--object", "car"],
        "wrong-type": [*base, "--video", str(avi), "--object", "car"],
        "directory": [*base, "--video", str(folder), "--object", "car"],
        "empty-noun": [*base, "--video", str(video), "--object", ""],
        "blank-noun": [*base, "--video", str(video), "--object", "   "],
        "long-noun": [*base, "--video", str(video), "--object", "x" * 41],
        "zero-duration": [*sam_args(video, "--yes", duration="0")],
        "negative-duration": [*sam_args(video, "--yes", duration="-5")],
        "nan-duration": [*sam_args(video, "--yes", duration="nan")],
        "word-duration": [*sam_args(video, "--yes", duration="ten")],
        "zero-fps": [*sam_args(video, "--yes", "--fps", "0")],
        "infinite-fps": [*sam_args(video, "--yes", "--fps", "inf")],
        "negative-max-cost": [*sam_args(video, "--yes", "--max-cost-usd", "-1")],
        "no-video": ["sam", "--object", "car", "--duration-seconds", "10", "--yes"],
        "no-object": ["sam", "--video", str(video), "--duration-seconds", "10", "--yes"],
        "no-duration": ["sam", "--video", str(video), "--object", "car", "--yes"],
        "no-command": [],
        "unknown-command": ["delete-everything", "--yes"],
    }


BAD_CASES = [
    "missing-file",
    "wrong-type",
    "directory",
    "empty-noun",
    "blank-noun",
    "long-noun",
    "zero-duration",
    "negative-duration",
    "nan-duration",
    "word-duration",
    "zero-fps",
    "infinite-fps",
    "negative-max-cost",
    "no-video",
    "no-object",
    "no-duration",
    "no-command",
    "unknown-command",
]


@pytest.mark.parametrize("case", BAD_CASES)
def test_invalid_input_exits_2_and_sends_nothing(
    settings: Settings, tmp_path: Path, video: Path, case: str
) -> None:
    transport = _ok_transport()
    code, _ = run(_bad_argvs(tmp_path, video)[case], settings, transport)
    assert code == 2
    assert transport.requests == []


def test_a_forty_character_noun_is_accepted(settings: Settings, video: Path) -> None:
    argv = [
        "sam",
        "--video",
        str(video),
        "--object",
        " " + "x" * 40 + " ",
        "--duration-seconds",
        "5",
    ]
    assert run(argv, settings, _ok_transport())[0] == 0


def test_a_video_at_the_size_limit_is_refused(
    settings: Settings, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spike, "MAX_VIDEO_BYTES", len(VIDEO_BYTES))
    transport = _ok_transport()
    code, output = run(sam_args(video, "--yes"), settings, transport)
    assert code == 2
    assert transport.requests == []
    assert "100 MB" in output


def test_a_video_just_under_the_size_limit_is_accepted(
    settings: Settings, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spike, "MAX_VIDEO_BYTES", len(VIDEO_BYTES) + 1)
    assert run(sam_args(video, "--yes"), settings, _ok_transport())[0] == 0


def test_the_size_limit_is_100_mb() -> None:
    assert spike.MAX_VIDEO_BYTES == 100_000_000


def test_a_file_error_during_a_live_run_exits_1_without_a_traceback(
    settings: Settings, video: Path
) -> None:
    transport = FakeTransport({"/files": PermissionError("the video is locked")})
    code, output = run(sam_args(video, "--yes"), settings, transport)
    assert code == 1
    assert "FAIL" in output
    assert "the video is locked" in output


# --- Running the file directly ----------------------------------------------------------------


@pytest.mark.parametrize("argv", [["--help"], ["check-key", "--help"]])
def test_the_file_runs_directly_from_any_folder(tmp_path: Path, argv: list[str]) -> None:
    # Only --help is used: it exits before the settings (and any .env) are read.
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "usage:" in result.stdout


def test_importing_the_script_leaves_sys_path_alone() -> None:
    before = list(sys.path)
    _load_script()
    assert sys.path == before
