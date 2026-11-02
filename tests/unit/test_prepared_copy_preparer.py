"""PreparedCopyPreparer: reuse a video that already is the 5 fps copy, byte for byte.

Re-encoding would change the file's bytes, and so the content hash an upload's request
fingerprint is made from; copying keeps a recording made earlier replayable.
"""

import json
from pathlib import Path

import pytest

from askfootage.adapters.media.ffmpeg import CommandResult, PreparedCopyPreparer
from askfootage.ports.video_store import VideoPreparationError


class Runner:
    def __init__(self, *, frames: str, duration: str) -> None:
        self.calls: list[list[str]] = []
        self._reply = json.dumps(
            {
                "streams": [
                    {"nb_frames": frames, "duration": duration, "width": 1920, "height": 1080}
                ],
                "format": {"duration": duration},
            }
        )

    def __call__(self, args: list[str], *, timeout: float) -> CommandResult:
        self.calls.append(args)
        return CommandResult(0, self._reply, "")


def which(name: str) -> str | None:
    return f"/fake/{name}"


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "in" / "prepared.mp4"
    path.parent.mkdir()
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(range(200)))
    return path


def test_the_copy_is_byte_identical_and_described(source: Path, tmp_path: Path) -> None:
    runner = Runner(frames="47", duration="9.400000")
    prepared = PreparedCopyPreparer(runner=runner, which=which).prepare(source, tmp_path / "out")
    assert prepared.path.read_bytes() == source.read_bytes()
    assert (prepared.frame_count, prepared.fps, prepared.width, prepared.height) == (
        47,
        5.0,
        1920,
        1080,
    )
    assert prepared.duration_seconds == pytest.approx(9.4)


def test_ffmpeg_never_encodes(source: Path, tmp_path: Path) -> None:
    runner = Runner(frames="47", duration="9.400000")
    PreparedCopyPreparer(runner=runner, which=which).prepare(source, tmp_path / "out")
    assert runner.calls and all("ffprobe" in call[0] for call in runner.calls)


def test_a_video_that_is_not_five_frames_per_second_is_refused(
    source: Path, tmp_path: Path
) -> None:
    runner = Runner(frames="300", duration="10.000000")  # 30 fps
    with pytest.raises(VideoPreparationError, match="5 fps"):
        PreparedCopyPreparer(runner=runner, which=which).prepare(source, tmp_path / "out")
    assert not (tmp_path / "out" / "prepared.mp4").exists()


def test_description_without_copying(source: Path) -> None:
    runner = Runner(frames="49", duration="9.800000")
    described = PreparedCopyPreparer(runner=runner, which=which).describe(source)
    assert described.frame_count == 49
    assert described.path == source.resolve()
