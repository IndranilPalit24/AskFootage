"""FfmpegVideoPreparer, tested offline through a scripted command runner.

No test here starts ffmpeg except the last one, which builds a tiny clip with ffmpeg's
built-in test source and is skipped when ffmpeg or ffprobe is not installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from askfootage.adapters.media import ffmpeg as ffmpeg_module
from askfootage.adapters.media.ffmpeg import (
    ENCODE_TIMEOUT_SECONDS,
    MAX_SOURCE_BYTES,
    PREPARED_FILE_NAME,
    PROBE_TIMEOUT_SECONDS,
    CommandResult,
    FfmpegVideoPreparer,
    run_command,
)
from askfootage.ports.video_store import PreparedVideo, VideoPreparationError, VideoPreparer

FFMPEG = "/fake/bin/ffmpeg"
FFPROBE = "/fake/bin/ffprobe"
SECRET_STDERR = "stderr-detail-that-must-not-leak"


def fake_which(name: str) -> str | None:
    return {"ffmpeg": FFMPEG, "ffprobe": FFPROBE}.get(name)


def probe_json(nb_frames: str | None = "10", duration: str | None = "2.000000") -> str:
    stream: dict[str, Any] = {}
    if nb_frames is not None:
        stream["nb_frames"] = nb_frames
    if duration is not None:
        stream["duration"] = duration
    return json.dumps({"streams": [stream], "format": {"duration": "2.100000"}})


Step = CommandResult | BaseException


class FakeRunner:
    """Answers each call with the next scripted step and records what it was asked to run.

    When ffmpeg is called it writes a few bytes to the output path (the last argument),
    the way a real encode would, before answering.
    """

    def __init__(self, steps: list[Step], *, write_output: bool = True) -> None:
        self.steps = list(steps)
        self.calls: list[tuple[Any, float | None]] = []
        self.write_output = write_output

    def __call__(self, args: list[str], *, timeout: float) -> CommandResult:
        self.calls.append((args, timeout))
        if self.write_output and args and args[0] == FFMPEG:
            Path(args[-1]).write_bytes(b"encoded")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def ok(stdout: str = "") -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="")


def happy_runner() -> FakeRunner:
    return FakeRunner([ok(), ok(probe_json())])


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "in" / "clip.mp4"
    path.parent.mkdir()
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    return path


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    path = tmp_path / "out"
    path.mkdir()
    return path


def make(runner: FakeRunner, **kwargs: Any) -> FfmpegVideoPreparer:
    return FfmpegVideoPreparer(runner=runner, which=fake_which, **kwargs)


def expected_encode_args(source: Path, dest: Path, demuxer: str = "mov") -> list[str]:
    return [
        FFMPEG,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-protocol_whitelist",
        "file",
        "-f",
        demuxer,
        "-i",
        str(source.resolve()),
        "-vf",
        "fps=5",
        "-r",
        "5",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-an",
        "-movflags",
        "+faststart",
        str((dest / "prepared.mp4").resolve()),
    ]


def assert_safe_message(error: BaseException, tmp_path: Path) -> None:
    message = str(error)
    assert message
    assert str(tmp_path) not in message
    assert str(tmp_path.resolve()) not in message
    assert "/fake/bin" not in message
    assert SECRET_STDERR not in message


# --- the happy path -----------------------------------------------------------------------


def test_it_satisfies_the_preparer_port() -> None:
    preparer: VideoPreparer = FfmpegVideoPreparer()
    assert isinstance(preparer, FfmpegVideoPreparer)


def test_the_encode_command_is_this_exact_argument_list(source: Path, dest: Path) -> None:
    runner = happy_runner()
    make(runner).prepare(source, dest)

    args, _ = runner.calls[0]
    assert type(args) is list
    assert all(type(arg) is str for arg in args)
    assert args == expected_encode_args(source, dest)


def test_the_encode_drops_audio_and_forces_five_fps_h264(source: Path, dest: Path) -> None:
    runner = happy_runner()
    make(runner).prepare(source, dest)

    args, _ = runner.calls[0]
    assert "-an" in args
    assert args[args.index("-vf") + 1] == "fps=5"
    assert args[args.index("-r") + 1] == "5"
    assert args[args.index("-c:v") + 1] == "libx264"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert args[args.index("-movflags") + 1] == "+faststart"


def test_the_probe_command_is_this_exact_argument_list(source: Path, dest: Path) -> None:
    runner = happy_runner()
    make(runner).prepare(source, dest)

    args, _ = runner.calls[1]
    assert type(args) is list
    assert args == [
        FFPROBE,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=nb_frames,duration:format=duration",
        "-of",
        "json",
        str((dest / "prepared.mp4").resolve()),
    ]


def test_every_call_gets_its_timeout(source: Path, dest: Path) -> None:
    runner = FakeRunner([ok(), ok(probe_json(nb_frames=None)), ok(counted_json(10))])
    make(runner).prepare(source, dest)

    timeouts = [timeout for _, timeout in runner.calls]
    assert timeouts == [ENCODE_TIMEOUT_SECONDS, PROBE_TIMEOUT_SECONDS, PROBE_TIMEOUT_SECONDS]


def test_timeouts_can_be_set(source: Path, dest: Path) -> None:
    runner = happy_runner()
    make(runner, encode_timeout_seconds=7.5, probe_timeout_seconds=1.5).prepare(source, dest)

    assert [timeout for _, timeout in runner.calls] == [7.5, 1.5]


def test_the_timeout_constants_are_positive_and_bounded() -> None:
    assert 0 < PROBE_TIMEOUT_SECONDS <= ENCODE_TIMEOUT_SECONDS <= 3600


def test_it_returns_the_prepared_video_described_by_the_probe(source: Path, dest: Path) -> None:
    prepared = make(happy_runner()).prepare(source, dest)

    assert prepared == PreparedVideo(
        path=(dest / "prepared.mp4").resolve(),
        fps=5.0,
        duration_seconds=2.0,
        frame_count=10,
    )
    assert PREPARED_FILE_NAME == "prepared.mp4"


def test_the_stream_duration_wins_over_the_container_duration(source: Path, dest: Path) -> None:
    runner = FakeRunner([ok(), ok(probe_json(nb_frames="12", duration="2.400000"))])
    prepared = make(runner).prepare(source, dest)

    assert prepared.duration_seconds == pytest.approx(2.4)
    assert prepared.frame_count == 12


def test_the_container_duration_is_used_when_the_stream_has_none(source: Path, dest: Path) -> None:
    runner = FakeRunner([ok(), ok(probe_json(duration="N/A"))])
    prepared = make(runner).prepare(source, dest)

    assert prepared.duration_seconds == pytest.approx(2.1)


def counted_json(frames: int | str) -> str:
    return json.dumps({"streams": [{"nb_read_frames": str(frames)}]})


@pytest.mark.parametrize("nb_frames", [None, "N/A", "0", "", "abc"])
def test_frames_are_counted_when_the_header_does_not_give_them(
    source: Path, dest: Path, nb_frames: str | None
) -> None:
    runner = FakeRunner([ok(), ok(probe_json(nb_frames=nb_frames)), ok(counted_json(11))])
    prepared = make(runner).prepare(source, dest)

    assert prepared.frame_count == 11
    args, _ = runner.calls[2]
    assert type(args) is list
    assert args == [
        FFPROBE,
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=nb_read_frames",
        "-of",
        "json",
        str((dest / "prepared.mp4").resolve()),
    ]


def test_dest_dir_is_created_when_missing(source: Path, tmp_path: Path) -> None:
    dest = tmp_path / "new" / "deeper"
    prepared = make(happy_runner()).prepare(source, dest)

    assert prepared.path.parent == dest.resolve()
    assert dest.is_dir()


@pytest.mark.parametrize(
    ("name", "demuxer"),
    [
        ("clip.MP4", "mov"),
        ("clip.mov", "mov"),
        ("clip.MOV", "mov"),
        ("clip.mkv", "matroska"),
        ("clip.Mkv", "matroska"),
    ],
)
def test_the_input_format_is_forced_from_the_extension_in_any_case(
    dest: Path, tmp_path: Path, name: str, demuxer: str
) -> None:
    path = tmp_path / name
    path.write_bytes(b"x" * 32)
    runner = happy_runner()

    assert make(runner).prepare(path, dest).frame_count == 10
    args, _ = runner.calls[0]
    assert args == expected_encode_args(path, dest, demuxer)


def test_a_source_exactly_at_the_size_limit_is_accepted(source: Path, dest: Path) -> None:
    limit = source.stat().st_size
    assert make(happy_runner(), max_source_bytes=limit).prepare(source, dest).frame_count == 10


def test_a_relative_source_path_is_made_absolute_before_reaching_ffmpeg(
    source: Path, dest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(source.parent)
    runner = happy_runner()
    make(runner).prepare(Path("clip.mp4"), dest)

    args, _ = runner.calls[0]
    assert args[args.index("-i") + 1] == str(source.resolve())


# --- missing tools -----------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["ffmpeg", "ffprobe"])
def test_a_missing_tool_is_reported_with_how_to_install_it(
    source: Path, dest: Path, missing: str
) -> None:
    def which(name: str) -> str | None:
        return None if name == missing else fake_which(name)

    runner = happy_runner()
    with pytest.raises(VideoPreparationError) as caught:
        FfmpegVideoPreparer(runner=runner, which=which).prepare(source, dest)

    message = str(caught.value)
    assert missing in message
    assert "PATH" in message
    assert "winget install Gyan.FFmpeg" in message
    assert runner.calls == []


# --- bad sources -------------------------------------------------------------------------


def test_a_missing_source_is_refused(dest: Path, tmp_path: Path) -> None:
    runner = happy_runner()
    with pytest.raises(VideoPreparationError) as caught:
        make(runner).prepare(tmp_path / "nope.mp4", dest)

    assert "not found" in str(caught.value)
    assert_safe_message(caught.value, tmp_path)
    assert runner.calls == []


def test_a_directory_source_is_refused(dest: Path, tmp_path: Path) -> None:
    folder = tmp_path / "folder.mp4"
    folder.mkdir()
    runner = happy_runner()
    with pytest.raises(VideoPreparationError) as caught:
        make(runner).prepare(folder, dest)

    assert_safe_message(caught.value, tmp_path)
    assert runner.calls == []


@pytest.mark.parametrize("name", ["clip.avi", "clip.txt", "clip", "clip.mp4.exe", "mp4", ".mp4x"])
def test_a_source_of_the_wrong_type_is_refused(dest: Path, tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"x" * 32)
    runner = happy_runner()
    with pytest.raises(VideoPreparationError) as caught:
        make(runner).prepare(path, dest)

    assert ".mp4" in str(caught.value)
    assert_safe_message(caught.value, tmp_path)
    assert runner.calls == []


def test_a_source_over_the_size_limit_is_refused(source: Path, dest: Path, tmp_path: Path) -> None:
    limit = source.stat().st_size - 1
    runner = happy_runner()
    with pytest.raises(VideoPreparationError) as caught:
        make(runner, max_source_bytes=limit).prepare(source, dest)

    assert "too large" in str(caught.value)
    assert_safe_message(caught.value, tmp_path)
    assert runner.calls == []


def test_an_empty_source_is_refused(dest: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    runner = happy_runner()
    with pytest.raises(VideoPreparationError):
        make(runner).prepare(empty, dest)
    assert runner.calls == []


def test_the_default_size_limit_is_200_mib_like_the_upload_limit() -> None:
    assert MAX_SOURCE_BYTES == 200 * 1024 * 1024
    assert FfmpegVideoPreparer().max_source_bytes == MAX_SOURCE_BYTES


# --- failures ----------------------------------------------------------------------------


def test_a_failed_encode_raises_a_short_safe_error_and_leaves_no_output(
    source: Path, dest: Path, tmp_path: Path
) -> None:
    runner = FakeRunner([CommandResult(1, "", f"{tmp_path} {SECRET_STDERR}")])
    with pytest.raises(VideoPreparationError) as caught:
        make(runner).prepare(source, dest)

    assert "exit code 1" in str(caught.value)
    assert len(str(caught.value)) < 200
    assert_safe_message(caught.value, tmp_path)
    assert not (dest / "prepared.mp4").exists()


def test_an_encode_timeout_raises_a_safe_error_and_leaves_no_output(
    source: Path, dest: Path, tmp_path: Path
) -> None:
    timeout = subprocess.TimeoutExpired(
        [FFMPEG, str(source)], ENCODE_TIMEOUT_SECONDS, stderr=SECRET_STDERR
    )
    runner = FakeRunner([timeout])
    with pytest.raises(VideoPreparationError) as caught:
        make(runner).prepare(source, dest)

    assert "timed out" in str(caught.value)
    assert_safe_message(caught.value, tmp_path)
    assert caught.value.__cause__ is None
    assert not (dest / "prepared.mp4").exists()


def test_a_tool_that_cannot_start_raises_a_safe_error(
    source: Path, dest: Path, tmp_path: Path
) -> None:
    runner = FakeRunner([PermissionError(13, "denied", f"{tmp_path}/ffmpeg")])
    with pytest.raises(VideoPreparationError) as caught:
        make(runner).prepare(source, dest)

    assert_safe_message(caught.value, tmp_path)
    assert caught.value.__cause__ is None


def test_an_encode_that_writes_nothing_is_a_failure(source: Path, dest: Path) -> None:
    runner = FakeRunner([ok(), ok(probe_json())], write_output=False)
    with pytest.raises(VideoPreparationError):
        make(runner).prepare(source, dest)


def test_a_failed_probe_raises_a_safe_error_and_removes_the_output(
    source: Path, dest: Path, tmp_path: Path
) -> None:
    runner = FakeRunner([ok(), CommandResult(2, "", SECRET_STDERR)])
    with pytest.raises(VideoPreparationError) as caught:
        make(runner).prepare(source, dest)

    assert "exit code 2" in str(caught.value)
    assert_safe_message(caught.value, tmp_path)
    assert not (dest / "prepared.mp4").exists()


def test_a_probe_timeout_raises_a_safe_error(source: Path, dest: Path, tmp_path: Path) -> None:
    runner = FakeRunner([ok(), subprocess.TimeoutExpired([FFPROBE], PROBE_TIMEOUT_SECONDS)])
    with pytest.raises(VideoPreparationError) as caught:
        make(runner).prepare(source, dest)

    assert "timed out" in str(caught.value)
    assert_safe_message(caught.value, tmp_path)
    assert not (dest / "prepared.mp4").exists()


BAD_PROBE_OUTPUTS: list[str] = [
    "",
    "not json",
    "[]",
    json.dumps({"streams": []}),
    json.dumps({"streams": "x"}),
    json.dumps({"streams": [1]}),
    json.dumps({"streams": [{"nb_frames": "10", "duration": "N/A"}], "format": {}}),
    json.dumps({"streams": [{"nb_frames": "10", "duration": "-1"}]}),
    json.dumps({"streams": [{"nb_frames": "10", "duration": "nan"}]}),
    json.dumps({"streams": [{"nb_frames": "10", "duration": "inf"}]}),
    json.dumps({"streams": [{"nb_frames": "-3", "duration": "2"}]}),
]


@pytest.mark.parametrize("stdout", BAD_PROBE_OUTPUTS)
def test_an_unusable_probe_result_is_a_safe_error(
    source: Path, dest: Path, tmp_path: Path, stdout: str
) -> None:
    runner = FakeRunner([ok(), ok(stdout), ok(counted_json("N/A"))])
    with pytest.raises(VideoPreparationError) as caught:
        make(runner).prepare(source, dest)

    assert_safe_message(caught.value, tmp_path)
    assert not (dest / "prepared.mp4").exists()


@pytest.mark.parametrize("counted", ["0", "N/A", "x"])
def test_a_video_with_no_countable_frames_is_refused(
    source: Path, dest: Path, counted: str
) -> None:
    runner = FakeRunner([ok(), ok(probe_json(nb_frames="N/A")), ok(counted_json(counted))])
    with pytest.raises(VideoPreparationError):
        make(runner).prepare(source, dest)


# --- the default runner ------------------------------------------------------------------


def test_the_default_runner_passes_a_list_with_a_timeout_and_no_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 3, stdout="out", stderr="err")

    monkeypatch.setattr(ffmpeg_module.subprocess, "run", fake_run)
    result = run_command(["tool", "-flag", "a b"], timeout=12.5)

    assert result == CommandResult(returncode=3, stdout="out", stderr="err")
    assert seen["args"] == ["tool", "-flag", "a b"]
    assert type(seen["args"]) is list
    kwargs = seen["kwargs"]
    assert kwargs.get("shell", False) is False
    assert kwargs["timeout"] == 12.5
    assert kwargs["capture_output"] is True
    assert kwargs["check"] is False
    assert kwargs["stdin"] is subprocess.DEVNULL


def test_the_default_runner_lets_a_timeout_through(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(ffmpeg_module.subprocess, "run", fake_run)
    with pytest.raises(subprocess.TimeoutExpired):
        run_command(["tool"], timeout=1.0)


def test_the_preparer_uses_the_default_runner_and_which_unless_told_otherwise() -> None:
    preparer = FfmpegVideoPreparer()
    assert preparer.runner is run_command
    assert preparer.which is shutil.which


# --- with the real tools -----------------------------------------------------------------

REAL_FFMPEG = shutil.which("ffmpeg")
REAL_FFPROBE = shutil.which("ffprobe")


def _real_run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=120, check=True)


def _stream_types(ffprobe: str, path: Path) -> list[str]:
    out = _real_run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)]
    ).stdout
    return [stream["codec_type"] for stream in json.loads(out)["streams"]]


@pytest.mark.skipif(
    REAL_FFMPEG is None or REAL_FFPROBE is None, reason="ffmpeg and ffprobe are not installed"
)
def test_a_real_clip_becomes_a_silent_five_fps_h264_mp4(tmp_path: Path) -> None:
    assert REAL_FFMPEG is not None and REAL_FFPROBE is not None
    source = tmp_path / "source.MOV"
    _real_run(
        [
            REAL_FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=160x120:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-f",
            "mov",
            str(source),
        ]
    )
    assert sorted(_stream_types(REAL_FFPROBE, source)) == ["audio", "video"]

    prepared = FfmpegVideoPreparer().prepare(source, tmp_path / "out")

    assert prepared.path == (tmp_path / "out" / "prepared.mp4").resolve()
    assert prepared.path.is_file()
    assert prepared.fps == 5.0
    assert prepared.frame_count == 10
    assert prepared.duration_seconds == pytest.approx(2.0, abs=0.25)
    assert _stream_types(REAL_FFPROBE, prepared.path) == ["video"]
    details = json.loads(
        _real_run(
            [
                REAL_FFPROBE,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,pix_fmt,avg_frame_rate",
                "-of",
                "json",
                str(prepared.path),
            ]
        ).stdout
    )["streams"][0]
    assert details == {"codec_name": "h264", "pix_fmt": "yuv420p", "avg_frame_rate": "5/1"}


@pytest.mark.skipif(
    REAL_FFMPEG is None or REAL_FFPROBE is None, reason="ffmpeg and ffprobe are not installed"
)
def test_a_playlist_disguised_as_an_mp4_is_refused_by_the_real_tools(tmp_path: Path) -> None:
    other = tmp_path / "other.mp4"
    other.write_bytes(b"not for reading")
    disguised = tmp_path / "disguised.mp4"
    disguised.write_text(
        f"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1.0,\n{other.as_uri()}\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )

    with pytest.raises(VideoPreparationError) as caught:
        FfmpegVideoPreparer().prepare(disguised, tmp_path / "out")

    assert_safe_message(caught.value, tmp_path)
    assert not (tmp_path / "out" / "prepared.mp4").exists()


def test_a_source_that_is_the_output_file_is_refused_and_left_alone(dest: Path) -> None:
    source = dest / "prepared.mp4"
    source.write_bytes(b"original bytes")
    runner = FakeRunner([CommandResult(1, "", "")])

    with pytest.raises(VideoPreparationError):
        make(runner).prepare(source, dest)

    assert runner.calls == []
    assert source.read_bytes() == b"original bytes"
