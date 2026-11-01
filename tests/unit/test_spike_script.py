"""Behaviour of scripts/api_spike.py (check-key and sam), tested fully offline.

Every test hands main() a Settings built directly with the fake key "test-key-not-real",
a data directory under tmp_path and an offline transport: a FakeTransport that answers by
path, or a MetaHttpClient wired to httpx.MockTransport. Nothing reaches the network, no
test passes --live to a real client and nothing reads the real settings.
"""

import importlib.util
import io
import json
import subprocess
import sys
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
from askfootage.ports.video_store import PreparedVideo, VideoPreparationError
from askfootage.settings import ConfigurationError, Settings

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "api_spike.py"
FAKE_KEY = "test-key-not-real"
BASE_URL = "https://api.example.test/v1"
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


def _ok_transport(sam_body: str = SAM_REPLY) -> FakeTransport:
    return FakeTransport(
        {"/files": RawResponse(200, FILE_REPLY), "/responses": RawResponse(200, sam_body)}
    )


class FakePreparer:
    """Stands in for the ffmpeg preparer: records calls, writes a small prepared.mp4."""

    def __init__(self, fail: str | None = None, frames: int = 100) -> None:
        self.calls: list[tuple[Path, Path]] = []
        self.fail = fail
        self.frames = frames

    def prepare(self, source: Path, dest_dir: Path) -> PreparedVideo:
        self.calls.append((source, dest_dir))
        if self.fail:
            raise VideoPreparationError(self.fail)
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / "prepared.mp4"
        out.write_bytes(b"prepared bytes")
        return PreparedVideo(
            path=out, fps=5.0, duration_seconds=self.frames / 5, frame_count=self.frames
        )


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
    clip.write_bytes(b"fake video bytes")
    return clip


def run(
    argv: list[str], settings: Settings, transport: Any = None, **kwargs: Any
) -> tuple[int, str]:
    out = io.StringIO()
    code = spike.main(argv, settings=settings, transport=transport, out=out, **kwargs)
    return code, out.getvalue()


def live(video: Path, *extra: str) -> list[str]:
    objects = [] if "--object" in extra else ["--object", "person"]
    return ["sam", "--live", "--video", str(video), *objects, *extra]


# --- check-key: one distinct result and exit code per category -------------------------------


def test_exit_codes_are_distinct_per_category() -> None:
    codes = [c for name, c in spike.EXIT_CODES.items() if not name.startswith("OK")]
    assert len(codes) == len(set(codes))
    assert spike.EXIT_CODES["OK_KEY_AND_MODEL"] == 0


@pytest.mark.parametrize(
    ("status", "body", "result"),
    [
        (401, "unauthorized", "KEY_REJECTED"),
        (403, "forbidden", "KEY_REJECTED"),
        (402, "payment required", "NO_CREDITS"),
        (403, "You exceeded your current quota", "NO_CREDITS"),
        (429, "insufficient credits on this account", "NO_CREDITS"),
        (404, "model not found", "MODEL_NOT_FOUND"),
        (429, "slow down", "RATE_LIMITED"),
        (500, "boom", "UNEXPECTED"),
        (400, "input video is required", "OK_KEY_AND_MODEL"),
        (422, "unprocessable", "OK_KEY_AND_MODEL"),
        (400, "billing not set up", "NO_CREDITS"),
    ],
)
def test_check_key_error_statuses_raised_by_the_client(
    settings: Settings, status: int, body: str, result: str
) -> None:
    transport = FakeTransport({"/responses": MetaApiError(status, body)})
    code, output = run(["check-key"], settings, transport)
    assert f"RESULT: {result}" in output
    assert f"HTTP status: {status}" in output
    assert code == spike.EXIT_CODES[result]
    assert len(transport.requests) == 1


def test_check_key_non_2xx_raw_reply_is_classified_too(settings: Settings) -> None:
    code, output = run(["check-key"], settings, FakeTransport({"/responses": RawResponse(404, "")}))
    assert "RESULT: MODEL_NOT_FOUND" in output
    assert code == 13


def test_check_key_ok(settings: Settings) -> None:
    transport = FakeTransport({"/responses": RawResponse(200, '{"output_text": "OK"}')})
    code, output = run(["check-key"], settings, transport)
    assert code == 0
    assert "RESULT: OK" in output
    assert "HTTP status: 200" in output
    (request,) = transport.requests
    assert request.json_body is not None
    assert request.json_body == {"model": "sam-3.1", "input": "person"}
    ledger = settings.data_dir / "spike" / "spend-ledger.jsonl"
    assert '"estimate": "0.001"' in ledger.read_text("utf-8")


def test_check_key_network_error(settings: Settings) -> None:
    transport = FakeTransport({"/responses": MetaConnectionError("down")})
    code, output = run(["check-key"], settings, transport)
    assert "RESULT: NETWORK_ERROR" in output
    assert code == 15


def test_check_key_missing_key_sends_nothing(tmp_path: Path) -> None:
    transport = FakeTransport()
    code, output = run(["check-key"], _settings(tmp_path, key=None), transport)
    assert "RESULT: KEY_MISSING" in output
    assert code == 10
    assert transport.requests == []


def test_check_key_configuration_error_from_the_client_is_key_missing(settings: Settings) -> None:
    transport = FakeTransport({"/responses": ConfigurationError("no key")})
    assert run(["check-key"], settings, transport)[0] == 10


def test_check_key_dry_run_sends_nothing_and_needs_no_key(tmp_path: Path) -> None:
    transport = FakeTransport()
    code, output = run(["check-key", "--dry-run"], _settings(tmp_path, key=None), transport)
    assert code == 0
    assert transport.requests == []
    assert "nothing was sent" in output.lower()
    assert "/responses" in output
    assert "sam-3.1" in output


def test_check_key_goes_through_the_real_client_with_a_429_that_outlasts_retries(
    settings: Settings,
) -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429, text="slow")))
    client = MetaHttpClient(settings, http=http, sleep=lambda _s: None)
    code, output = run(["check-key"], settings, client)
    assert "RESULT: RATE_LIMITED" in output
    assert code == 14


def test_check_key_real_client_402(settings: Settings) -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(402, text="pay")))
    client = MetaHttpClient(settings, http=http, sleep=lambda _s: None)
    assert run(["check-key"], settings, client)[0] == 12


def test_the_key_and_headers_never_appear_in_check_key_output(settings: Settings) -> None:
    body = f"echo {FAKE_KEY} Authorization: Bearer {FAKE_KEY}"
    transport = FakeTransport({"/responses": MetaApiError(401, body)})
    _, output = run(["check-key"], settings, transport)
    assert FAKE_KEY not in output


def test_old_yes_flag_is_a_harmless_no_op_for_check_key(settings: Settings) -> None:
    transport = FakeTransport({"/responses": RawResponse(200, "{}")})
    assert run(["check-key", "--yes"], settings, transport)[0] == 0


# --- sam plan (no --live) --------------------------------------------------------------------


def test_plan_prints_the_exact_shapes_and_sends_nothing(settings: Settings, video: Path) -> None:
    transport = _ok_transport()
    code, output = run(
        ["sam", "--video", str(video)], settings, transport, probe_duration=lambda _p: 20.0
    )
    assert code == 0
    assert transport.requests == []
    assert str(video) in output
    assert "frames at 5 fps: 100" in output
    assert "estimated cost: $0.06" in output
    assert "3 passes" in output
    for noun in ("person", "box", "hand"):
        assert f'"text": "{noun}"' in output
    assert "POST" in output and "/files" in output
    assert "purpose = user_data" in output
    assert "/responses" in output
    assert '"model": "sam-3.1"' in output
    assert '"text": "person"' in output
    assert '"stream": true' in output
    assert '"include_confidence": "true"' in output


def test_plan_needs_no_key_and_creates_no_files(tmp_path: Path, video: Path) -> None:
    keyless = _settings(tmp_path, key=None)
    code, _ = run(["sam", "--video", str(video)], keyless, probe_duration=lambda _p: 1.0)
    assert code == 0
    assert not (tmp_path / "data").exists()


def test_plan_reports_a_missing_default_video_and_the_synthetic_fallback(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # no videos/clip1.mp4 here
    code, output = run(["sam"], settings, probe_duration=lambda _p: None)
    assert code == 0
    assert "NOT FOUND" in output
    assert "SYNTHETIC" in output
    assert "frames at 5 fps: 30" in output


def test_plan_for_a_missing_named_video_says_live_would_refuse(
    settings: Settings, tmp_path: Path
) -> None:
    code, output = run(["sam", "--video", str(tmp_path / "nope.mp4")], settings)
    assert code == 0
    assert "NOT FOUND" in output
    assert "refuse" in output


def test_yes_is_refused_for_sam_and_sends_nothing(settings: Settings, video: Path) -> None:
    transport = _ok_transport()
    code, output = run(["sam", "--yes", "--video", str(video)], settings, transport)
    assert code == 2
    assert "--live" in output
    assert transport.requests == []


# --- sam --live --------------------------------------------------------------------------------


def test_live_uploads_then_asks_with_the_file_id(settings: Settings, video: Path) -> None:
    transport, preparer = _ok_transport(), FakePreparer()
    code, output = run(live(video), settings, transport, preparer=preparer)
    assert code == 0
    upload, ask = transport.requests
    assert upload.path == "/files"
    assert upload.upload is not None
    assert upload.upload.purpose == "user_data"
    assert upload.upload.path.name == "prepared.mp4"
    assert ask.json_body is not None
    assert ask.json_body["model"] == "sam-3.1"
    assert ask.json_body["stream"] is True
    assert ask.json_body["metadata"] == {"include_confidence": "true"}
    content = ask.json_body["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "person"}
    assert content[1] == {"type": "input_video", "file_id": "file-abc123"}
    assert preparer.calls[0][0] == video


def test_live_prints_status_and_the_raw_streamed_events_and_saves_them(
    settings: Settings, video: Path
) -> None:
    code, output = run(live(video), settings, _ok_transport(), preparer=FakePreparer())
    assert code == 0
    assert "RESULT: OK" in output
    assert "HTTP status: 200" in output
    assert "event: delta" in output
    assert 'data: {"frame": 1}' in output
    saved = json.loads((settings.data_dir / "spike" / "sam_clip_person.json").read_text("utf-8"))
    assert saved["http_status"] == 200
    assert saved["raw"] == SAM_REPLY
    assert "file-abc123" in saved["files_reply"]


def test_a_long_reply_prints_80_lines_and_the_file_path(settings: Settings, video: Path) -> None:
    body = "\n".join(f"data: {i}" for i in range(200))
    _, output = run(live(video), settings, _ok_transport(body), preparer=FakePreparer())
    assert "data: 79" in output
    assert "data: 80\n" not in output
    assert "120 more lines" in output
    assert "sam_clip_person.json" in output


def test_live_records_spend_and_a_ledger(settings: Settings, video: Path) -> None:
    _, output = run(live(video), settings, _ok_transport(), preparer=FakePreparer(frames=1000))
    assert "total spend recorded (all runs): $0.20 of $25 cap" in output
    ledger = settings.data_dir / "spike" / "spend-ledger.jsonl"
    lines = [json.loads(x) for x in ledger.read_text("utf-8").splitlines()]
    assert [x["path"] for x in lines] == ["/files", "/responses"]
    assert lines[1]["outcome"] == "sent"


def test_a_repeat_live_run_is_served_from_the_recording(settings: Settings, video: Path) -> None:
    run(live(video), settings, _ok_transport(), preparer=FakePreparer())
    second = _ok_transport()
    code, output = run(live(video), settings, second, preparer=FakePreparer())
    assert code == 0
    assert second.requests == []
    assert "saved recording" in output


def test_live_without_a_video_falls_back_to_a_synthetic_one_and_says_so(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    made: list[Path] = []

    def synthesize(target: Path) -> int:
        target.write_bytes(b"synthetic")
        made.append(target)
        return 0

    preparer = FakePreparer()
    code, output = run(
        ["sam", "--live"], settings, _ok_transport(), preparer=preparer, synthesize=synthesize
    )
    assert code == 0
    assert "FALLBACK" in output and "SYNTHETIC" in output
    assert preparer.calls[0][0] == made[0]


def test_live_uses_videos_clip1_when_it_exists(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "clip1.mp4").write_bytes(b"real")
    synthesized: list[Path] = []
    preparer = FakePreparer()
    code, output = run(
        ["sam", "--live"],
        settings,
        _ok_transport(),
        preparer=preparer,
        synthesize=lambda t: synthesized.append(t) or 0,
    )
    assert code == 0
    assert synthesized == []
    assert "FALLBACK" not in output
    assert preparer.calls[0][0].name == "clip1.mp4"


def test_live_with_a_missing_named_video_is_refused_without_fallback(
    settings: Settings, tmp_path: Path
) -> None:
    transport = _ok_transport()
    code, output = run(
        ["sam", "--live", "--video", str(tmp_path / "nope.mp4")],
        settings,
        transport,
        preparer=FakePreparer(),
        synthesize=lambda _t: pytest.fail("must not fall back"),
    )
    assert code == 2
    assert "INVALID" in output
    assert transport.requests == []


def test_live_without_a_key_sends_nothing(tmp_path: Path, video: Path) -> None:
    transport = _ok_transport()
    code, output = run(live(video), _settings(tmp_path, key=None), transport)
    assert code == 10
    assert "RESULT: KEY_MISSING" in output
    assert transport.requests == []


def test_a_prep_failure_exits_2_and_sends_nothing(settings: Settings, video: Path) -> None:
    transport = _ok_transport()
    code, output = run(live(video), settings, transport, preparer=FakePreparer(fail="no ffmpeg"))
    assert code == 2
    assert "no ffmpeg" in output
    assert transport.requests == []


def test_the_hard_cap_blocks_the_paid_call(tmp_path: Path, video: Path) -> None:
    settings = _settings(tmp_path, cap="0.005")
    transport = _ok_transport()
    code, output = run(live(video), settings, transport, preparer=FakePreparer())
    assert code == 2
    assert "REFUSED" in output
    assert [r.path for r in transport.requests] == ["/files"]  # the free upload only


@pytest.mark.parametrize(
    ("error", "result"),
    [
        (MetaApiError(401, "no"), "KEY_REJECTED"),
        (MetaApiError(402, "pay"), "NO_CREDITS"),
        (MetaApiError(404, "gone"), "MODEL_NOT_FOUND"),
        (MetaApiError(429, "slow"), "RATE_LIMITED"),
        (MetaConnectionError("down"), "NETWORK_ERROR"),
    ],
)
def test_live_failures_get_the_same_categories(
    settings: Settings, video: Path, error: Exception, result: str
) -> None:
    transport = FakeTransport({"/files": RawResponse(200, FILE_REPLY), "/responses": error})
    code, output = run(live(video), settings, transport, preparer=FakePreparer())
    assert f"RESULT: {result}" in output
    assert code == spike.EXIT_CODES[result]


def test_an_upload_reply_without_a_file_id_exits_1(settings: Settings, video: Path) -> None:
    transport = FakeTransport({"/files": RawResponse(200, "{}")})
    code, output = run(live(video), settings, transport, preparer=FakePreparer())
    assert code == 1
    assert [r.path for r in transport.requests] == ["/files"]


def test_the_key_is_scrubbed_from_output_and_the_saved_file(
    settings: Settings, video: Path
) -> None:
    body = f"data: leaked {FAKE_KEY}\n"
    _, output = run(live(video), settings, _ok_transport(body), preparer=FakePreparer())
    assert FAKE_KEY not in output
    saved = (settings.data_dir / "spike" / "sam_clip_person.json").read_text("utf-8")
    assert FAKE_KEY not in saved
    assert "[REDACTED]" in saved


def test_invalid_noun_exits_2(settings: Settings, video: Path) -> None:
    assert run(["sam", "--object", "x" * 41, "--video", str(video)], settings)[0] == 2


# --- running the file --------------------------------------------------------------------------


def test_python_dash_m_scripts_api_spike_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.api_spike", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "check-key" in result.stdout


def test_the_file_runs_directly_from_any_folder(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "sam", "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--live" in result.stdout


def test_importing_the_script_leaves_sys_path_alone() -> None:
    before = list(sys.path)
    _load_script()
    assert sys.path == before


def test_invalid_settings_exit_2(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Settings:
        raise ConfigurationError("MAX_RUN_COST_USD: must be greater than 0")

    monkeypatch.setattr(spike, "load_settings", broken)
    out = io.StringIO()
    assert spike.main(["check-key"], transport=FakeTransport(), out=out) == 2


def test_a_400_from_a_sam_call_is_not_reported_as_ok(settings: Settings, video: Path) -> None:
    transport = FakeTransport(
        {"/files": RawResponse(200, FILE_REPLY), "/responses": MetaApiError(400, "bad body")}
    )
    code, output = run(live(video), settings, transport, preparer=FakePreparer())
    assert "RESULT: UNEXPECTED" in output
    assert code == 1


def test_no_muse_model_is_referenced() -> None:
    assert "muse" not in SCRIPT.read_text("utf-8").lower()


# --- one pass per concept, one upload per clip ---------------------------------------------------


def _asked_nouns(transport: FakeTransport) -> list[str]:
    return [
        r.json_body["input"][0]["content"][0]["text"]
        for r in transport.requests
        if r.json_body is not None
    ]


def test_default_concepts_are_person_box_and_hand_as_separate_passes(
    settings: Settings, video: Path
) -> None:
    transport = _ok_transport()
    code, output = run(
        ["sam", "--live", "--video", str(video)], settings, transport, preparer=FakePreparer()
    )
    assert code == 0
    assert [r.path for r in transport.requests] == [
        "/files",
        "/responses",
        "/responses",
        "/responses",
    ]
    assert _asked_nouns(transport) == ["person", "box", "hand"]
    for noun in ("person", "box", "hand"):
        assert (settings.data_dir / "spike" / f"sam_clip_{noun}.json").is_file()
    assert "PASS clip / box" in output


def test_two_clips_are_each_uploaded_once_and_asked_three_times(
    settings: Settings, tmp_path: Path
) -> None:
    clips = []
    for name in ("one.mp4", "two.mp4"):
        clip = tmp_path / name
        clip.write_bytes(b"x")
        clips.append(clip)

    class DistinctPreparer(FakePreparer):
        def prepare(self, source: Path, dest_dir: Path) -> PreparedVideo:
            prepared = super().prepare(source, dest_dir)
            prepared.path.write_bytes(source.name.encode())
            return prepared

    class NumberedFiles(FakeTransport):
        def send(self, request: MetaRequest) -> RawResponse:
            if request.path == "/files":
                self.requests.append(request)
                return RawResponse(200, f'{{"id": "file-{len(self.requests)}"}}')
            return super().send(request)

    transport = NumberedFiles({"/responses": RawResponse(200, SAM_REPLY)})
    preparer = DistinctPreparer()
    code, _ = run(
        ["sam", "--live", "--video", str(clips[0]), "--video", str(clips[1])],
        settings,
        transport,
        preparer=preparer,
    )
    assert code == 0
    assert [r.path for r in transport.requests].count("/files") == 2
    assert [r.path for r in transport.requests].count("/responses") == 6
    assert [c[1].name for c in preparer.calls] == ["one", "two"]
    assert all(c[1].parent.name == "prepared" for c in preparer.calls)


def test_a_failed_pass_stops_the_run_with_its_own_category(settings: Settings, video: Path) -> None:
    transport = FakeTransport(
        {"/files": RawResponse(200, FILE_REPLY), "/responses": MetaApiError(429, "slow down")}
    )
    code, output = run(
        ["sam", "--live", "--video", str(video)], settings, transport, preparer=FakePreparer()
    )
    assert code == 14
    assert "RATE_LIMITED" in output
    assert _asked_nouns(transport) == ["person"]
