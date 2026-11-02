"""FfmpegSnapshotRenderer: one frame of the working copy with the boxes drawn on it.

Most tests use a scripted command runner. The last one builds a tiny clip with ffmpeg's test
source and checks the pixels; it is skipped when ffmpeg is not installed.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from askfootage.adapters.media.ffmpeg import CommandResult
from askfootage.adapters.media.snapshots import (
    NEUTRAL_COLOR,
    OBJECT_COLOR,
    FfmpegSnapshotRenderer,
)
from askfootage.ports.snapshots import SnapshotBox

BOXES = (SnapshotBox("object", 100.4, 200, 300.6, 400), SnapshotBox("person", 50, 60, 500, 700))


class Runner:
    def __init__(self, returncode: int = 0, write: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.write = write

    def __call__(self, args: list[str], *, timeout: float) -> CommandResult:
        self.calls.append(args)
        if self.write and self.returncode == 0:
            Path(args[-1]).write_bytes(b"\xff\xd8jpeg")
        return CommandResult(self.returncode, "", "SECRET stderr C:\\hidden")


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "clip2" / "prepared.mp4"
    path.parent.mkdir()
    path.write_bytes(b"video")
    return path


def renderer(video: Path, runner: Runner) -> FfmpegSnapshotRenderer:
    return FfmpegSnapshotRenderer(
        lambda recording_id: video if recording_id == "clip2" else None,
        runner=runner,
        which=lambda name: f"/fake/{name}",
    )


def test_it_selects_the_exact_frame_and_writes_one_image(video: Path, tmp_path: Path) -> None:
    runner = Runner()
    out = tmp_path / "out.jpg"
    renderer(video, runner).render("clip2", 6, BOXES, out)
    (args,) = runner.calls
    assert args[0] == "/fake/ffmpeg" and str(video) in args and args[-1] == str(out)
    graph = args[args.index("-vf") + 1]
    assert graph.startswith("select=eq(n\\,6)")
    assert args[args.index("-frames:v") + 1] == "1"
    assert out.read_bytes().startswith(b"\xff\xd8")


def test_the_object_is_drawn_in_red_and_the_person_in_a_neutral_colour(
    video: Path, tmp_path: Path
) -> None:
    runner = Runner()
    renderer(video, runner).render("clip2", 6, BOXES, tmp_path / "o.jpg")
    graph = runner.calls[0][runner.calls[0].index("-vf") + 1]
    boxes = graph.split(",drawbox=")[1:]
    assert len(boxes) == 2
    assert OBJECT_COLOR == "red"
    assert f"color={NEUTRAL_COLOR}" in boxes[0] and "x=50:y=60:w=450:h=640" in boxes[0]
    assert "color=red" in boxes[1] and "x=100:y=200:w=201:h=200" in boxes[1]


def test_the_object_is_drawn_last_so_it_stays_on_top(video: Path, tmp_path: Path) -> None:
    runner = Runner()
    renderer(video, runner).render("clip2", 6, BOXES, tmp_path / "o.jpg")
    assert runner.calls[0][runner.calls[0].index("-vf") + 1].rstrip().endswith("t=6")


def test_a_box_past_the_frame_edge_is_kept_inside_non_negative_numbers(
    video: Path, tmp_path: Path
) -> None:
    runner = Runner()
    odd = (SnapshotBox("object", -5, -3, 10, 10),)
    renderer(video, runner).render("clip2", 0, odd, tmp_path / "o.jpg")
    assert "x=0:y=0:w=10:h=10" in runner.calls[0][runner.calls[0].index("-vf") + 1]


def test_an_unknown_recording_is_an_error_and_nothing_runs(tmp_path: Path, video: Path) -> None:
    runner = Runner()
    with pytest.raises(FileNotFoundError):
        renderer(video, runner).render("nope", 1, BOXES, tmp_path / "o.jpg")
    assert runner.calls == []


def test_a_failed_run_is_a_safe_error(video: Path, tmp_path: Path) -> None:
    with pytest.raises(OSError) as caught:
        renderer(video, Runner(returncode=1)).render("clip2", 6, BOXES, tmp_path / "o.jpg")
    assert "SECRET" not in str(caught.value) and "hidden" not in str(caught.value)


def test_no_output_file_is_an_error(video: Path, tmp_path: Path) -> None:
    with pytest.raises(OSError):
        renderer(video, Runner(write=False)).render("clip2", 6, BOXES, tmp_path / "o.jpg")


def test_a_negative_frame_is_refused(video: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        renderer(video, Runner()).render("clip2", -1, BOXES, tmp_path / "o.jpg")


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg is not installed",
)
def test_real_ffmpeg_draws_red_and_grey_on_the_chosen_frame(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    make = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "color=c=black:s=640x360:r=5:d=2", "-pix_fmt", "yuv420p", str(clip),
    ]  # fmt: skip
    subprocess.run(make, check=True)
    out = tmp_path / "snap.jpg"
    boxes = (SnapshotBox("object", 200, 100, 300, 200), SnapshotBox("person", 50, 40, 150, 340))
    FfmpegSnapshotRenderer(lambda _id: clip).render("x", 3, boxes, out)
    assert out.read_bytes()[:2] == b"\xff\xd8"

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        crop = [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            str(out),
            "-vf",
            f"format=rgb24,crop=1:1:{x}:{y}",
        ]
        crop += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        data = subprocess.run(crop, check=True, capture_output=True).stdout
        return data[0], data[1], data[2]

    red = pixel(250, 101)  # on the object box's top edge
    grey = pixel(100, 41)  # on the person box's top edge
    inside = pixel(250, 150)  # inside the box: untouched black
    assert red[0] > 180 and red[1] < 90 and red[2] < 90
    assert abs(grey[0] - grey[1]) < 25 and abs(grey[1] - grey[2]) < 25 and grey[0] > 100
    assert max(inside) < 40
