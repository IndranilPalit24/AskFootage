"""The stored box maps exactly onto the player for any displayed size (object-fit: contain)."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "verify_box_frames", ROOT / "scripts" / "verify_box_frames.py"
)
assert _spec is not None and _spec.loader is not None
vbf = importlib.util.module_from_spec(_spec)
sys.modules["verify_box_frames"] = vbf
_spec.loader.exec_module(vbf)

SIZES = [(1920, 1080), (960, 540), (800, 600), (1280, 720)]
# frames with a box, inside a gap, before the first and after the last stored point
BOX_FRAMES = [6, 15, 23, 31, 34, 39, 46]
GAP_FRAMES = [3, 24, 30, 35, 38, 43, 47]


def _library_box_track() -> dict[int, tuple[float, float, float, float]]:
    if not vbf.LIBRARY.exists():
        pytest.skip("data/real/library.sqlite is missing")
    tracks = vbf.load_tracks("clip2", vbf.BOX_LABEL)
    if not tracks:
        pytest.skip("no stored cardboard box track for clip2")
    return {f: b for t in tracks.values() for f, b in t.items()}


@pytest.mark.parametrize("size", SIZES)
def test_stored_box_is_scaled_exactly_into_the_player(size):
    pw, ph = size
    track = _library_box_track()
    scale = min(pw / 1920, ph / 1080)
    off_x, off_y = (pw - 1920 * scale) / 2, (ph - 1080 * scale) / 2
    for frame in BOX_FRAMES:
        x1, y1, x2, y2 = track[frame]
        got = vbf.box_to_player((x1, y1, x2, y2), pw, ph)
        want = (x1 * scale + off_x, y1 * scale + off_y, x2 * scale + off_x, y2 * scale + off_y)
        assert got == pytest.approx(want, abs=1e-9)
        # the box stays inside the picture area of the player
        assert off_x - 1e-9 <= got[0] < got[2] <= pw - off_x + 1e-9
        assert off_y - 1e-9 <= got[1] < got[3] <= ph - off_y + 1e-9


def test_letterboxed_player_offsets_vertically():
    got = vbf.box_to_player((0, 0, 1920, 1080), 800, 600)
    assert got == pytest.approx((0, 75, 800, 525))


def test_full_size_player_is_the_identity():
    assert vbf.box_to_player((10, 20, 30, 40), 1920, 1080) == (10, 20, 30, 40)


def test_gaps_give_no_box():
    track = _library_box_track()
    for frame in GAP_FRAMES:
        assert frame not in track


def test_frame_time_is_frame_over_five():
    assert [f / vbf.ANALYSIS_FPS for f in (0, 5, 23)] == [0.0, 1.0, 4.6]
