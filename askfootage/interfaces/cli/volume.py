r"""Command line for the generated demo volume: invented cameras, zones and recordings.

    .venv\Scripts\python.exe -m askfootage.interfaces.cli.volume --status
    .venv\Scripts\python.exe -m askfootage.interfaces.cli.volume --add
    .venv\Scripts\python.exe -m askfootage.interfaces.cli.volume --remove

--add puts 18 cameras, their zones and seven days of recordings into the library, every row
tagged origin 'demo_volume'. Running it twice changes nothing the second time. --remove deletes
every origin 'demo_volume' row and puts the camera counter back, so the library is as it was
before --add (rows and counter; only SQLite's free pages stay). --status prints the row count
per table, split by origin. The volume holds no tracks, clips, saved clips or search results,
and its recordings have no video file.

The library is the real one, DATA_DIR/real/library.sqlite, unless --demo picks the demo
database (DATA_DIR/demo.sqlite) or --database names a file. A file that does not exist is
never created. Exit codes: 0 done, 1 refused or failed (message on stderr), 2 bad command line.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.adapters.sqlite.volume_seed import (
    REAL_ORIGIN,
    VOLUME_ORIGIN,
    add_volume,
    remove_volume,
    volume_status,
)
from askfootage.ports.library_store import LibraryError
from askfootage.settings import ConfigurationError, Settings, load_settings

REAL_LIBRARY = Path("real") / "library.sqlite"
"""The real-mode library, inside DATA_DIR."""
DEMO_LIBRARY = Path("demo.sqlite")
"""The demo-mode library, inside DATA_DIR."""
FAILED_MESSAGE = "error: the command could not be completed (check the database file)"


def build_parser() -> argparse.ArgumentParser:
    """The argument parser: exactly one of --add, --remove, --status."""
    parser = argparse.ArgumentParser(prog="askfootage-volume", description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--add", action="store_true", help="add the volume (idempotent)")
    action.add_argument("--remove", action="store_true", help="remove every volume row")
    action.add_argument("--status", action="store_true", help="count rows per table and origin")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--demo", action="store_true", help="use DATA_DIR/demo.sqlite")
    target.add_argument("--database", type=Path, help="use this library file instead")
    return parser


def format_status(status: dict[str, dict[str, int]]) -> str:
    """The status as a plain table: one row per table, a column per origin."""
    width = max(len(table) for table in status)
    lines = [f"{'table':<{width}}  {REAL_ORIGIN:>8}  {VOLUME_ORIGIN:>11}"]
    lines += [
        f"{table:<{width}}  {counts[REAL_ORIGIN]:>8}  {counts[VOLUME_ORIGIN]:>11}"
        for table, counts in status.items()
    ]
    return "\n".join(lines)


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
        if args.database is not None:
            path = args.database
        else:
            settings = settings or load_settings()
            path = settings.data_dir / (DEMO_LIBRARY if args.demo else REAL_LIBRARY)
        if not path.is_file():
            print("error: the library file does not exist (it is never created here)", file=err)
            return 1
        store = SqliteLibraryStore(path)
        if args.add:
            added = add_volume(store)
            print("volume added" if added else "volume already present; nothing changed", file=out)
        elif args.remove:
            removed = remove_volume(store)
            print(
                f"volume removed ({removed} cameras)" if removed else "no volume; nothing changed",
                file=out,
            )
        print(format_status(volume_status(store)), file=out)
    except ConfigurationError as error:
        print(f"error: {error}", file=err)
        return 1
    except LibraryError as error:
        print(f"error: {error}", file=err)
        return 1
    except (ValueError, OSError):  # never a traceback, a path or a cause's text
        print(FAILED_MESSAGE, file=err)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
