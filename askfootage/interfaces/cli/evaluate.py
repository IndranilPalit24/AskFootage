r"""Command line for scoring predicted relations against a labels file.

    .venv\Scripts\python.exe -m askfootage.interfaces.cli.evaluate labels\demo.json [--json]

Reads the stored tracks of the labels' video (DATA_DIR/<video id>/tracks.json, written by
the ingest command), runs the relation rules and prints precision, recall, f1 and IoU per
relation. The format of the labels file is in labels/README.md. A video with no stored
tracks is an error, not a table of zeros. Evaluating never calls Meta, so --fake is
accepted but changes nothing. Exit codes: 0 scored, 1 refused (message on stderr),
2 bad command line.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from askfootage.application.errors import ApplicationError
from askfootage.application.evaluate import (
    DEFAULT_IOU_THRESHOLD,
    RelationScore,
    evaluate,
    load_labels,
    predict_relations,
)
from askfootage.interfaces.cli.wiring import build_track_store
from askfootage.ports.track_store import TrackDataError
from askfootage.settings import ConfigurationError, Settings, load_settings

FAILED_MESSAGE = "error: the command could not be completed (check the arguments and the files)"
_COLUMNS = ("relation", "pred", "truth", "prec", "recall", "f1", "iou", "matched", "mIoU")


def build_parser() -> argparse.ArgumentParser:
    """The argument parser."""
    parser = argparse.ArgumentParser(prog="askfootage-evaluate", description=__doc__)
    parser.add_argument("labels", type=Path, help="a labels JSON file")
    parser.add_argument("--iou", type=float, default=DEFAULT_IOU_THRESHOLD, metavar="THRESHOLD")
    parser.add_argument("--json", action="store_true", dest="as_json", help="print JSON")
    parser.add_argument("--fake", action="store_true", help="accepted; has no effect")
    return parser


def _table(report: dict[str, RelationScore]) -> str:
    rows = [_COLUMNS] + [
        (
            key,
            str(s.predicted),
            str(s.truth),
            f"{s.precision:.3f}",
            f"{s.recall:.3f}",
            f"{s.f1:.3f}",
            f"{s.frame_iou:.3f}",
            str(s.matched),
            f"{s.mean_matched_iou:.3f}",
        )
        for key, s in report.items()
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(len(_COLUMNS))]
    lines = ("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)) for row in rows)
    return "\n".join(line.rstrip() for line in lines)


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run the command; returns the exit code. `settings` is for tests; None loads them."""
    out = out or sys.stdout
    err = err or sys.stderr
    args = build_parser().parse_args(argv)
    if not 0.0 < args.iou <= 1.0:
        print("error: --iou must be above 0 and at most 1", file=err)
        return 1
    try:
        settings = settings or load_settings()
        labels = load_labels(args.labels)
        predicted = predict_relations(build_track_store(settings), labels)
        report = evaluate(predicted, labels, args.iou)
    except (ApplicationError, ConfigurationError) as error:
        print(f"error: {getattr(error, 'message', None) or error}", file=err)
        return 1
    except TrackDataError:
        print("error: the stored tracks for that video are unreadable", file=err)
        return 1
    except (ValueError, OSError):  # never a traceback, a path or a cause's text
        print(FAILED_MESSAGE, file=err)
        return 1
    if args.as_json:
        relations = {key: score.as_dict() for key, score in report.items()}
        print(json.dumps({"video_id": labels.video_id, "relations": relations}, indent=2), file=out)
    else:
        print(_table(report), file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
