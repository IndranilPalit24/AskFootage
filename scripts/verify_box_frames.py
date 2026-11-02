"""Check that stored box tracks sit on the real objects in the playable video.

For a recording it reads the stored tracks (read-only), extracts frames from the playable
source video with ffmpeg at t = frame / 5 s, draws the cardboard box in thick red and the
people in light grey, and writes JPEGs plus a contact sheet under data/verify/<id>/.
It also prints a table of frame, time and box coordinates.

    .venv/Scripts/python.exe scripts/verify_box_frames.py clip2 videos/clip2.mp4
    .venv/Scripts/python.exe scripts/verify_box_frames.py clip1 videos/clip1.mp4

box_to_player() is the pure mapping from a stored box (pixels of the analysed frame) to
the pixels of a player that shows the video with object-fit: contain.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ANALYSIS_FPS = 5
FRAME_W, FRAME_H = 1920, 1080
ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT / "data" / "real" / "library.sqlite"
BOX_LABEL = "cardboard box"
RED = (255, 0, 0)
GREY = (200, 200, 200)

Box = tuple[float, float, float, float]


def box_to_player(
    box: Box,
    player_w: float,
    player_h: float,
    frame_w: float = FRAME_W,
    frame_h: float = FRAME_H,
) -> Box:
    """Map a box in video pixels to player pixels with object-fit: contain letterboxing."""
    scale = min(player_w / frame_w, player_h / frame_h)
    off_x = (player_w - frame_w * scale) / 2
    off_y = (player_h - frame_h * scale) / 2
    x1, y1, x2, y2 = box
    return (x1 * scale + off_x, y1 * scale + off_y, x2 * scale + off_x, y2 * scale + off_y)


def load_tracks(recording: str, label: str, library: Path = LIBRARY) -> dict[int, dict[int, Box]]:
    """{track_id: {frame: box}} for one recording and label, read without writing."""
    uri = f"file:{library.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        rows = con.execute(
            "SELECT t.track_id, p.frame, p.x1, p.y1, p.x2, p.y2 FROM tracks t "
            "JOIN track_points p ON p.track_row = t.id "
            "WHERE t.recording_id = ? AND t.label = ? ORDER BY t.track_id, p.frame",
            (recording, label),
        ).fetchall()
    finally:
        con.close()
    out: dict[int, dict[int, Box]] = {}
    for tid, frame, x1, y1, x2, y2 in rows:
        out.setdefault(tid, {})[frame] = (x1, y1, x2, y2)
    return out


def pick_frames(box_frames: set[int], last_frame: int) -> list[int]:
    """Every stored box frame plus a few before, after and inside gaps."""
    frames = set(box_frames)
    if box_frames:
        lo, hi = min(box_frames), max(box_frames)
        frames.update(
            {max(0, lo - 3), max(0, lo - 1), min(last_frame, hi + 1), min(last_frame, hi + 3)}
        )
        frames.update(f for f in range(lo, hi + 1) if f not in box_frames)
    else:
        frames.update(range(0, last_frame + 1, 6))
    return sorted(frames)


def extract_frame(ffmpeg: str, video: Path, t: float, out: Path) -> None:
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(out),
        ],
        check=True,
    )


def main(argv: list[str]) -> int:
    recording, video = argv[1], ROOT / argv[2]
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("ffmpeg not found on PATH")
        return 1
    from PIL import Image, ImageDraw

    out_dir = ROOT / "data" / "verify" / recording
    out_dir.mkdir(parents=True, exist_ok=True)
    boxes = load_tracks(recording, BOX_LABEL)
    people = load_tracks(recording, "person")
    box_by_frame = {f: b for track in boxes.values() for f, b in track.items()}
    all_frames = {f for t in people.values() for f in t} | set(box_by_frame)
    last = max(all_frames) if all_frames else 0
    frames = pick_frames(set(box_by_frame), last)
    print(f"{'frame':>5} {'t':>6}  box (x1, y1, x2, y2)")
    tiles = []
    for f in frames:
        t = f / ANALYSIS_FPS
        path = out_dir / f"f{f:03d}_t{t:.1f}.jpg"
        extract_frame(ffmpeg, video, t, path)
        img = Image.open(path).convert("RGB")
        d = ImageDraw.Draw(img)
        for track in people.values():
            if f in track:
                d.rectangle(track[f], outline=GREY, width=4)
        b = box_by_frame.get(f)
        if b:
            d.rectangle(b, outline=RED, width=8)
        d.rectangle((0, 0, 330, 44), fill=(0, 0, 0))
        d.text(
            (8, 8),
            f"t={t:.1f}s frame={f} {'BOX' if b else 'no box'}",
            fill=(255, 255, 255),
            font_size=28,
        )
        img.save(path, quality=90)
        tiles.append(img.resize((480, 270)))
        shown = "none" if b is None else ", ".join(f"{v:.0f}" for v in b)
        print(f"{f:>5} {t:>5.1f}s  {shown}")
    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 480, rows * 270), (0, 0, 0))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % cols) * 480, (i // cols) * 270))
    sheet.save(out_dir / "contact_sheet.jpg", quality=85)
    print(f"wrote {len(tiles)} frames and contact_sheet.jpg to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
