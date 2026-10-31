r"""Command line for ingesting a video and adding a concept to an ingested one.

    .venv\Scripts\python.exe -m askfootage.interfaces.cli.ingest ingest vid-1 clip.mp4 --fake
    .venv\Scripts\python.exe -m askfootage.interfaces.cli.ingest add-concept vid-1 forklift --fake

--fake uses a deterministic demo perception: no API key, no ffmpeg, no spend. Without it
the real perception is needed, which this build does not have yet (exit 1, with the
"not configured" message, before any ffmpeg work). Tracks are kept as JSON under
DATA_DIR/<video id>/tracks.json.
The spending cap (MAX_RUN_COST_USD) is cumulative across runs: it is tracked in
DATA_DIR/ledger. Without --fake each call is priced from the video's frame count and
--cost-per-concept can only raise that estimate. A call that fails after it may have been
sent still counts as spent. Concepts are lower-cased; one outside the vocabulary prints a
warning on stderr and is stored anyway. A video whose source file changed needs --force.
Exit codes: 0 done, 1 refused or failed (message on stderr), 2 bad command line.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO

from askfootage.application.add_concept import add_video_concept
from askfootage.application.errors import ApplicationError
from askfootage.application.ingest_video import IngestResult, ingest_video
from askfootage.domain.vocabulary import OBJECT_NOUNS
from askfootage.interfaces.cli.wiring import build_services
from askfootage.ports.track_store import TrackDataError
from askfootage.settings import ConfigurationError, Settings, load_settings

DEFAULT_CONCEPTS = ("person", "cardboard box")
FAILED_MESSAGE = "error: the command could not be completed (check the arguments and the files)"


def _cost(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("must be an amount in dollars") from None
    if not value.is_finite() or value < 0:
        raise argparse.ArgumentTypeError("must be an amount in dollars, 0 or more")
    return value


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for both commands."""
    parser = argparse.ArgumentParser(prog="askfootage-ingest", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("ingest", "add-concept"):
        sub = commands.add_parser(name)
        sub.add_argument("video_id")
        if name == "ingest":
            sub.add_argument("source", type=Path, help="the video file")
            sub.add_argument(
                "-c",
                "--concept",
                action="append",
                dest="concepts",
                help="object noun to find; repeat for several (default: person, cardboard box)",
            )
        else:
            sub.add_argument("concept", help="the object noun to add")
        sub.add_argument("--force", action="store_true", help="redo concepts already stored")
        sub.add_argument("--fake", action="store_true", help="demo perception: no key, no spend")
        sub.add_argument("--cost-per-concept", type=_cost, default=None, metavar="USD")
    return parser


def _vocabulary_warnings(concepts: Sequence[str]) -> list[str]:
    """A warning per concept outside the vocabulary: it is stored, but no question reaches it."""
    known = ", ".join(sorted(OBJECT_NOUNS))
    return [
        f"warning: '{c}' is not in the vocabulary ({known}); stored, but search cannot ask about it"
        for c in concepts
        if c not in OBJECT_NOUNS
    ]


def _report(result: IngestResult, out: TextIO) -> None:
    for concept, count in result.track_counts.items():
        print(f"{result.video_id}: {concept}: {count} track(s) stored", file=out)
    for concept in result.skipped:
        print(f"{result.video_id}: {concept}: already stored, skipped", file=out)


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run a command; returns the exit code. `settings` is for tests; None loads them."""
    out = out or sys.stdout
    err = err or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        settings = settings or load_settings()
        services = build_services(settings, fake=args.fake, cost_per_concept=args.cost_per_concept)
        if args.command == "ingest":
            concepts = args.concepts or list(DEFAULT_CONCEPTS)
            result = ingest_video(services, args.video_id, args.source, concepts, force=args.force)
        else:
            result = add_video_concept(services, args.video_id, args.concept, force=args.force)
    except (ApplicationError, ConfigurationError) as error:
        print(f"error: {getattr(error, 'message', None) or error}", file=err)
        return 1
    except TrackDataError:
        print("error: the stored tracks for that video are unreadable", file=err)
        return 1
    except (ValueError, OSError):  # never a traceback, a path or a cause's text
        print(FAILED_MESSAGE, file=err)
        return 1
    for warning in _vocabulary_warnings(list(result.track_counts) + list(result.skipped)):
        print(warning, file=err)
    _report(result, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
