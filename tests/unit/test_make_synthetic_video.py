"""scripts/make_synthetic_video.py: a short MP4 with a 'person' carrying an object into a region.

Frame drawing and the missing-ffmpeg message are tested offline; the real encode is skipped
when ffmpeg or ffprobe is not installed.
"""

import importlib.util
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_synthetic_video.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_synthetic_video_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


synth = _load()


def test_the_person_starts_outside_the_region_and_ends_inside() -> None:
    x0, y0, x1, y1 = synth.REGION
    first = synth.person_center(0, synth.FRAME_COUNT)
    last = synth.person_center(synth.FRAME_COUNT - 1, synth.FRAME_COUNT)
    assert not (x0 <= first[0] <= x1 and y0 <= first[1] <= y1)
    assert x0 <= last[0] <= x1 and y0 <= last[1] <= y1


def test_the_person_moves_every_frame() -> None:
    centers = [synth.person_center(i, synth.FRAME_COUNT) for i in range(synth.FRAME_COUNT)]
    assert len(set(centers)) == len(centers)


def test_a_frame_has_the_right_shape_and_shows_person_and_object() -> None:
    frame = synth.render_frame(10, synth.FRAME_COUNT)
    assert frame.shape == (synth.HEIGHT, synth.WIDTH, 3)
    assert frame.dtype.name == "uint8"
    cx, cy = synth.person_center(10, synth.FRAME_COUNT)
    assert tuple(frame[cy, cx]) == synth.PERSON_COLOR
    ox, oy = synth.object_center(10, synth.FRAME_COUNT)
    assert tuple(frame[oy, ox]) == synth.OBJECT_COLOR


def test_the_object_stays_with_the_person() -> None:
    for i in (0, 30, synth.FRAME_COUNT - 1):
        cx, cy = synth.person_center(i, synth.FRAME_COUNT)
        ox, oy = synth.object_center(i, synth.FRAME_COUNT)
        assert abs(ox - cx) <= synth.PERSON_RADIUS * 2
        assert abs(oy - cy) <= synth.PERSON_RADIUS * 2


def test_without_ffmpeg_it_says_so_clearly_and_exits_1(tmp_path: Path) -> None:
    out = io.StringIO()
    code = synth.main([str(tmp_path / "x.mp4")], which=lambda _name: None, out=out)
    assert code == 1
    assert "ffmpeg not found" in out.getvalue().lower()
    assert not (tmp_path / "x.mp4").exists()


def test_it_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / "x.mp4"
    target.write_bytes(b"keep me")
    out = io.StringIO()
    code = synth.main([str(target)], which=lambda _name: "ffmpeg", out=out)
    assert code == 2
    assert target.read_bytes() == b"keep me"


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are not installed",
)
def test_it_writes_a_real_h264_mp4(tmp_path: Path) -> None:
    target = tmp_path / "synthetic.mp4"
    out = io.StringIO()
    assert synth.main([str(target)], out=out) == 0
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height",
            "-of",
            "json",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["codec_name"] == "h264"
    assert (stream["width"], stream["height"]) == (synth.WIDTH, synth.HEIGHT)
