r"""Print what the labels say next to what the relation layer finds in the stored real clips.

    .venv\Scripts\python.exe -m scripts.evaluate_real_clips

Reads labels/clip1.json and labels/clip2.json (never changed by this tool) and the tracks that
scripts.ingest_real_clips stored in data/real/library.sqlite. Nothing is sent anywhere and no
setting is read. Exit codes: 0 printed, 2 refused.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from askfootage.adapters.sqlite.store import SqliteLibraryStore  # noqa: E402
from askfootage.adapters.sqlite.tracks import SqliteTrackStore  # noqa: E402
from askfootage.application.clip_labels import load_clip_labels  # noqa: E402
from askfootage.application.errors import ApplicationError  # noqa: E402
from askfootage.application.evaluate_clips import EventResult, evaluate_clip  # noqa: E402
from askfootage.ports.library_store import LibraryError  # noqa: E402
from scripts.ingest_real_clips import CLIPS  # noqa: E402


def _times(spans: Sequence[tuple[float, float]]) -> str:
    return ", ".join(f"{a:.1f}-{b:.1f} s" for a, b in spans) or "nothing found"


def _line(clip: str, row: EventResult) -> str:
    event = row.event
    expected = (
        f"{event.start_s:g} s"
        if event.start_s == event.end_s
        else f"{event.start_s:g}-{event.end_s:g} s"
    )
    iou = "" if row.iou is None else f" IoU {row.iou:.2f}"
    note = f" ({row.note})" if row.note else ""
    return (
        f"{clip}  {event.type:<11} {event.object:<7} {event.status:<11} expected {expected:<10} "
        f"found {_times(row.found):<24} {row.verdict.upper()}{iou}{note}"
    )


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(prog="python -m scripts.evaluate_real_clips")
    parser.add_argument("--data-dir", type=Path, default=Path("data") / "real")
    parser.add_argument("--labels-dir", type=Path, default=Path("labels"))
    args = parser.parse_args(argv)
    try:
        tracks = SqliteTrackStore(SqliteLibraryStore(args.data_dir / "library.sqlite"))
        scored = matched = 0
        for clip in CLIPS:
            labels = load_clip_labels(args.labels_dir / f"{clip}.json")
            result = evaluate_clip(labels, tracks, clip)
            scored, matched = scored + result.scored, matched + result.matched
            for row in result.rows:
                out.write(_line(clip, row) + "\n")
    except (ApplicationError, LibraryError, OSError) as error:
        out.write(f"REFUSED: {getattr(error, 'message', None) or type(error).__name__}\n")
        return 2
    out.write(f"scored {scored} confirmed event(s): {matched} matched\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
