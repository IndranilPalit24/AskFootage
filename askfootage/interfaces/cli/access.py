r"""Command line for demo access codes (a demo gate for the UI; it does not protect footage).

    .venv\Scripts\python.exe -m askfootage.interfaces.cli.access --create --label judges
    .venv\Scripts\python.exe -m askfootage.interfaces.cli.access --list
    .venv\Scripts\python.exe -m askfootage.interfaces.cli.access --revoke ID

--create prints the new 6-digit code once; only its hash is stored, so it cannot be shown
again. --list shows id, label, created time and state, never a code. --revoke stops a code
working. The library is the real one, DATA_DIR/real/library.sqlite, unless --demo picks
DATA_DIR/demo.sqlite or --database names a file. A file that does not exist is never created.
Exit codes: 0 done, 1 refused or failed (message on stderr), 2 bad command line.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from askfootage.adapters.sqlite.access_codes import SqliteAccessCodeStore
from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.interfaces.cli.volume import DEMO_LIBRARY, FAILED_MESSAGE, REAL_LIBRARY
from askfootage.ports.library_store import LibraryError
from askfootage.settings import ConfigurationError, Settings, load_settings


def build_parser() -> argparse.ArgumentParser:
    """The argument parser: exactly one of --create, --list, --revoke."""
    parser = argparse.ArgumentParser(prog="askfootage-access", description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--create", action="store_true", help="make a code (needs --label)")
    action.add_argument("--list", action="store_true", help="list codes, never the codes")
    action.add_argument("--revoke", metavar="ID", help="revoke the code with this id")
    parser.add_argument("--label", help="who the code is for, such as judges (with --create)")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--demo", action="store_true", help="use DATA_DIR/demo.sqlite")
    target.add_argument("--database", type=Path, help="use this library file instead")
    return parser


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
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.create and not args.label:
        parser.error("--create needs --label")
    if args.label and not args.create:
        parser.error("--label is only for --create")
    try:
        if args.database is not None:
            path = args.database
        else:
            settings = settings or load_settings()
            path = settings.data_dir / (DEMO_LIBRARY if args.demo else REAL_LIBRARY)
        if not path.is_file():
            print("error: the library file does not exist (it is never created here)", file=err)
            return 1
        codes = SqliteAccessCodeStore(SqliteLibraryStore(path))
        if args.create:
            made = codes.create_code(args.label)
            print(f"id {made.id}  label {made.label}", file=out)
            print(f"code {made.code}  (shown once; only a hash is stored)", file=out)
        elif args.list:
            for item in codes.list_codes():
                state = "revoked" if item.revoked else "active"
                stamp = item.created_at.strftime("%Y-%m-%d %H:%M:%S")
                print(f"{item.id}  {item.label}  {stamp}Z  {state}", file=out)
        else:
            if not codes.revoke_code(args.revoke):
                print("error: no active code with that id", file=err)
                return 1
            print("code revoked", file=out)
    except ConfigurationError as error:
        print(f"error: {error}", file=err)
        return 1
    except LibraryError as error:
        print(f"error: {error}", file=err)
        return 1
    except (ValueError, OSError):
        print(FAILED_MESSAGE, file=err)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
