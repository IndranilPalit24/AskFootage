"""scripts/prepare_clips.py: offline preparation of the real clips, tested without ffmpeg."""

import io
import shutil
import subprocess
from pathlib import Path

import pytest

from askfootage.adapters.media.ffmpeg import FfmpegVideoPreparer
from askfootage.ports.video_store import PreparedVideo, VideoPreparationError
from scripts import prepare_clips

REAL_FFMPEG = shutil.which("ffmpeg")
REAL_FFPROBE = shutil.which("ffprobe")


class FakePreparer:
    def __init__(self, frames: int, fail: str | None = None) -> None:
        self.frames = frames
        self.fail = fail
        self.calls: list[tuple[Path, Path]] = []

    def prepare(self, source: Path, dest_dir: Path) -> PreparedVideo:
        self.calls.append((source, dest_dir))
        if self.fail:
            raise VideoPreparationError(self.fail)
        return PreparedVideo(
            path=dest_dir / "prepared.mp4",
            fps=5.0,
            duration_seconds=self.frames / 5,
            frame_count=self.frames,
        )


def run(argv: list[str], tmp_path: Path, preparer: FakePreparer) -> tuple[int, str]:
    out = io.StringIO()
    code = prepare_clips.main(argv, data_dir=tmp_path / "data", out=out, preparer=preparer)
    return code, out.getvalue()


def test_prints_frame_count_and_cost_and_writes_under_data_prepared(tmp_path: Path) -> None:
    preparer = FakePreparer(frames=200)
    code, output = run(["videos/a.mp4"], tmp_path, preparer)
    assert code == 0
    assert preparer.calls == [(Path("videos/a.mp4"), tmp_path / "data" / "prepared" / "a")]
    assert "a: 200 frames at 5 fps" in output
    assert "estimated cost per request $0.04" in output
    assert "minimum" not in output


def test_a_short_clip_is_billed_at_the_fifty_frame_minimum(tmp_path: Path) -> None:
    _, output = run(["a.mp4"], tmp_path, FakePreparer(frames=47))
    assert "47 frames" in output
    assert "$0.01 (billed as 50: minimum)" in output


def test_defaults_to_both_real_clips(tmp_path: Path) -> None:
    preparer = FakePreparer(frames=60)
    run([], tmp_path, preparer)
    assert [c[0].stem for c in preparer.calls] == ["clip1", "clip2"]


def test_a_failed_preparation_is_refused_with_exit_2(tmp_path: Path) -> None:
    code, output = run(
        ["a.mp4"], tmp_path, FakePreparer(frames=1, fail="The source was not found.")
    )
    assert code == 2
    assert "REFUSED: The source was not found." in output


@pytest.mark.skipif(REAL_FFMPEG is None or REAL_FFPROBE is None, reason="ffmpeg is not installed")
def test_the_prepared_clip_has_no_audio_track(tmp_path: Path) -> None:
    source = tmp_path / "with_audio.mp4"
    subprocess.run(
        [REAL_FFMPEG, "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=2:rate=30",
         "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(source)],
        check=True,
    )  # fmt: skip
    out = io.StringIO()
    code = prepare_clips.main(
        [str(source)], data_dir=tmp_path / "data", out=out, preparer=FfmpegVideoPreparer()
    )
    assert code == 0
    prepared = tmp_path / "data" / "prepared" / "with_audio" / "prepared.mp4"
    streams = subprocess.run(
        [REAL_FFPROBE, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
         str(prepared)],
        check=True, capture_output=True, text=True,
    ).stdout.split()  # fmt: skip
    assert streams == ["video"]
