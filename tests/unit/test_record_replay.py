"""Behaviour of request fingerprints and the record-and-replay transports, all offline.

Recordings live in pytest's tmp_path. The live side is a scripted stand-in, except in one
test that wraps MetaHttpClient over httpx.MockTransport to prove a recording never holds
the key, even when the server echoes it back. The only key used is "test-key-not-real".
"""

import ast
import hashlib
import json
import socket
import sys
from dataclasses import fields
from inspect import signature
from pathlib import Path

import httpx
import pytest

from askfootage.adapters.meta import record_replay
from askfootage.adapters.meta.client import MetaHttpClient
from askfootage.adapters.meta.record_replay import RecordingTransport, ReplayTransport, fingerprint
from askfootage.adapters.meta.transport import (
    FileUpload,
    MetaConnectionError,
    MetaRequest,
    RawResponse,
    RecordingCorruptError,
    RecordingNotFoundError,
)
from askfootage.settings import load_settings

FAKE_KEY = "test-key-not-real"
REQUEST = MetaRequest("/responses", json_body={"model": "muse-test", "input": "hello"})
FINGERPRINT = fingerprint(REQUEST)
RECORDING_NAME = f"{FINGERPRINT}.json"


class ScriptedTransport:
    """Stands in for the live client: returns the given replies in order, logging each call."""

    def __init__(self, *replies: RawResponse) -> None:
        self._replies = list(replies)
        self.calls: list[MetaRequest] = []

    def send(self, request: MetaRequest) -> RawResponse:
        """Record the call and return the next scripted reply."""
        self.calls.append(request)
        return self._replies.pop(0)


class FailingTransport:
    """Stands in for a live client that cannot reach the API."""

    def send(self, request: MetaRequest) -> RawResponse:
        """Always fail, as an unreachable API would."""
        raise MetaConnectionError("simulated outage")


def _record(directory: Path, body: str = "first") -> None:
    RecordingTransport(ScriptedTransport(RawResponse(200, body)), directory).send(REQUEST)


def _entries(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def _video(path: Path, content: bytes = b"fake video bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _simulated_disk_failure(source: str, target: Path) -> None:
    raise OSError("simulated disk failure")


# --- Fingerprints -----------------------------------------------------------------------------


def test_fingerprint_is_the_sha256_of_compact_key_sorted_json() -> None:
    canonical = (
        '{"json_body":{"input":"hello","model":"muse-test"},"path":"/responses","upload":null}'
    )
    assert FINGERPRINT == hashlib.sha256(canonical.encode()).hexdigest()


def test_an_upload_fingerprint_hashes_the_file_content_and_purpose(tmp_path: Path) -> None:
    clip = _video(tmp_path / "clip.mp4")
    content_hash = hashlib.sha256(b"fake video bytes").hexdigest()
    canonical = (
        '{"json_body":null,"path":"/files",'
        f'"upload":{{"purpose":"user_data","sha256":"{content_hash}"}}}}'
    )
    request = MetaRequest("/files", upload=FileUpload(clip, "user_data"))
    assert fingerprint(request) == hashlib.sha256(canonical.encode()).hexdigest()


def test_fingerprint_ignores_key_order_in_the_body() -> None:
    first = MetaRequest("/responses", json_body={"model": "m", "options": {"x": 1, "y": 2}})
    second = MetaRequest("/responses", json_body={"options": {"y": 2, "x": 1}, "model": "m"})
    assert fingerprint(first) == fingerprint(second)


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param(
            MetaRequest("/responses", json_body={"model": "muse-other", "input": "hello"}),
            id="model",
        ),
        pytest.param(
            MetaRequest("/responses", json_body={"model": "muse-test", "input": "bye"}),
            id="input",
        ),
        pytest.param(
            MetaRequest("/other", json_body={"model": "muse-test", "input": "hello"}), id="path"
        ),
    ],
)
def test_fingerprint_changes_when_the_request_changes(changed: MetaRequest) -> None:
    assert fingerprint(changed) != FINGERPRINT


def test_the_same_file_under_another_name_has_the_same_fingerprint(tmp_path: Path) -> None:
    original = _video(tmp_path / "clip.mp4")
    renamed = _video(tmp_path / "elsewhere" / "renamed.mov")
    assert fingerprint(MetaRequest("/files", upload=FileUpload(original, "user_data"))) == (
        fingerprint(MetaRequest("/files", upload=FileUpload(renamed, "user_data")))
    )


@pytest.mark.parametrize(
    ("content", "purpose"),
    [(b"other video bytes", "user_data"), (b"fake video bytes", "other_purpose")],
    ids=["content", "purpose"],
)
def test_a_different_file_content_or_purpose_changes_the_fingerprint(
    tmp_path: Path, content: bytes, purpose: str
) -> None:
    base = fingerprint(
        MetaRequest("/files", upload=FileUpload(_video(tmp_path / "a"), "user_data"))
    )
    other = MetaRequest("/files", upload=FileUpload(_video(tmp_path / "b", content), purpose))
    assert fingerprint(other) != base


def test_nothing_secret_can_reach_a_fingerprint() -> None:
    # The only input is the request, and a request has no field for headers or keys.
    assert list(signature(fingerprint).parameters) == ["request"]
    assert [field.name for field in fields(MetaRequest)] == ["path", "json_body", "upload"]
    assert [field.name for field in fields(FileUpload)] == ["path", "purpose"]


# --- Recording and replaying ------------------------------------------------------------------


def test_a_recorded_reply_replays_identically(tmp_path: Path) -> None:
    reply = RawResponse(200, '{"id": "resp_1"}')
    assert RecordingTransport(ScriptedTransport(reply), tmp_path).send(REQUEST) == reply
    assert ReplayTransport(tmp_path).send(REQUEST) == reply


def test_recording_skips_the_live_call_when_a_recording_exists(tmp_path: Path) -> None:
    _record(tmp_path, "first")
    live = ScriptedTransport(RawResponse(200, "second"))
    assert RecordingTransport(live, tmp_path).send(REQUEST).body == "first"
    assert live.calls == []


def test_refresh_calls_the_live_side_again_and_overwrites_the_recording(tmp_path: Path) -> None:
    _record(tmp_path, "first")
    live = ScriptedTransport(RawResponse(200, "second"))
    assert RecordingTransport(live, tmp_path, refresh=True).send(REQUEST).body == "second"
    assert len(live.calls) == 1
    assert ReplayTransport(tmp_path).send(REQUEST).body == "second"


@pytest.mark.parametrize("status", [199, 300, 400, 429, 500])
def test_a_reply_outside_2xx_is_returned_but_never_saved(tmp_path: Path, status: int) -> None:
    reply = RawResponse(status, "error")
    assert RecordingTransport(ScriptedTransport(reply), tmp_path).send(REQUEST) == reply
    assert _entries(tmp_path) == []


def test_a_failed_live_call_saves_nothing(tmp_path: Path) -> None:
    with pytest.raises(MetaConnectionError):
        RecordingTransport(FailingTransport(), tmp_path).send(REQUEST)
    assert _entries(tmp_path) == []


def test_replaying_an_unrecorded_request_names_its_fingerprint_and_how_to_record_it(
    tmp_path: Path,
) -> None:
    with pytest.raises(RecordingNotFoundError) as excinfo:
        ReplayTransport(tmp_path).send(REQUEST)
    assert FINGERPRINT in str(excinfo.value)
    assert "RecordingTransport" in str(excinfo.value)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"{not json", id="bad-json"),
        pytest.param(b"\xff\xfe\x00", id="not-utf8"),
        pytest.param(b"[]", id="not-an-object"),
        pytest.param(json.dumps({"fingerprint": FINGERPRINT, "status": 200}), id="no-body"),
        pytest.param(json.dumps({"fingerprint": FINGERPRINT, "body": "ok"}), id="no-status"),
        pytest.param(json.dumps({"status": 200, "body": "ok"}), id="no-fingerprint"),
        pytest.param(
            json.dumps({"fingerprint": FINGERPRINT, "status": "200", "body": "ok"}),
            id="status-as-text",
        ),
        pytest.param(
            json.dumps({"fingerprint": FINGERPRINT, "status": 200, "body": None}),
            id="body-not-text",
        ),
        pytest.param(
            json.dumps({"fingerprint": "0" * 64, "status": 200, "body": "ok"}),
            id="someone-elses-fingerprint",
        ),
    ],
)
def test_a_damaged_recording_raises_recording_corrupt_error(
    tmp_path: Path, content: bytes | str
) -> None:
    recording = tmp_path / RECORDING_NAME
    recording.write_bytes(content if isinstance(content, bytes) else content.encode())
    with pytest.raises(RecordingCorruptError):
        ReplayTransport(tmp_path).send(REQUEST)


def test_recording_never_quietly_pays_to_replace_a_damaged_recording(tmp_path: Path) -> None:
    (tmp_path / RECORDING_NAME).write_text("{not json", encoding="utf-8")
    live = ScriptedTransport(RawResponse(200, "fresh"))
    with pytest.raises(RecordingCorruptError):
        RecordingTransport(live, tmp_path).send(REQUEST)
    assert live.calls == []


# --- The recording file -----------------------------------------------------------------------


def test_a_recording_is_indented_json_with_lf_line_endings_only(tmp_path: Path) -> None:
    _record(tmp_path, "line one\r\nline two")
    raw = (tmp_path / RECORDING_NAME).read_bytes()
    assert b"\r" not in raw
    assert raw.startswith(b'{\n  "')
    assert json.loads(raw.decode("utf-8")) == {
        "fingerprint": FINGERPRINT,
        "path": "/responses",
        "status": 200,
        "body": "line one\r\nline two",
    }


def test_saving_leaves_only_the_recording_behind(tmp_path: Path) -> None:
    _record(tmp_path)
    assert _entries(tmp_path) == [RECORDING_NAME]


def test_a_save_that_fails_midway_leaves_no_file_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record_replay.os, "replace", _simulated_disk_failure)
    with pytest.raises(OSError, match="simulated"):
        _record(tmp_path)
    assert _entries(tmp_path) == []


def test_a_failed_refresh_keeps_the_previous_recording_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(tmp_path, "first")
    monkeypatch.setattr(record_replay.os, "replace", _simulated_disk_failure)
    live = ScriptedTransport(RawResponse(200, "second"))
    with pytest.raises(OSError, match="simulated"):
        RecordingTransport(live, tmp_path, refresh=True).send(REQUEST)
    assert _entries(tmp_path) == [RECORDING_NAME]
    assert ReplayTransport(tmp_path).send(REQUEST).body == "first"


def test_recording_creates_its_directory(tmp_path: Path) -> None:
    directory = tmp_path / "recordings" / "muse"
    _record(directory)
    assert (directory / RECORDING_NAME).is_file()


def test_a_recording_never_holds_the_key_even_when_the_reply_echoes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("MAX_RUN_COST_USD", "DATA_DIR", "ASKFOOTAGE_DEMO"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("META_API_KEY", FAKE_KEY)
    monkeypatch.setenv("META_API_BASE_URL", "https://api.example.test/v1")

    def echo_the_header(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"echo": request.headers["Authorization"]})

    http = httpx.Client(transport=httpx.MockTransport(echo_the_header))
    live = MetaHttpClient(load_settings(env_file=None), http=http)
    RecordingTransport(live, tmp_path).send(REQUEST)

    saved = (tmp_path / RECORDING_NAME).read_text(encoding="utf-8")
    assert "Bearer " in saved  # the header really was echoed
    assert FAKE_KEY not in saved


# --- Offline guarantees -----------------------------------------------------------------------


def test_replay_works_with_the_network_switched_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(tmp_path, "ok")

    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("replay tried to use the network")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(httpx.Client, "send", no_network)
    assert ReplayTransport(tmp_path).send(REQUEST) == RawResponse(200, "ok")


@pytest.mark.parametrize("module", ["record_replay", "transport"])
def test_the_replay_side_imports_nothing_that_can_reach_the_network(module: str) -> None:
    source = Path(record_replay.__file__).with_name(f"{module}.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported |= {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    outside_stdlib = {
        name for name in imported if name.split(".")[0] not in sys.stdlib_module_names
    }
    assert outside_stdlib <= {"askfootage.adapters.meta.transport"}
