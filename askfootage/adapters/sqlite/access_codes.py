"""Demo access codes: 6-digit codes kept as salted hashes in the library's database.

This is a demo gate for the UI only. It does not protect footage; the rest of the API is not
authenticated. Only a salted scrypt hash is stored, never the code, so a code is shown once,
when it is created. Codes are not identities of people (ADR 0008): a label names a group
such as "judges".

SqliteAccessCodeStore borrows the library's connections and transactions (as
SqliteTrackStore does), so every write is one BEGIN IMMEDIATE transaction and values only
reach SQL as bound parameters. It touches the demo_access_codes table and no other.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.ports.library_store import LibraryError

CODE_DIGITS = 6
"""How many digits a demo access code has."""

MAX_LABEL_LENGTH = 40
"""Longest label, in characters (the schema's CHECK)."""

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
_MAX_NEW_CODE_TRIES = 50

_INSERT = """
    INSERT INTO demo_access_codes (id, code_hash, salt, label, created_at)
    VALUES (?, ?, ?, ?, ?)
"""
_ACTIVE = "SELECT code_hash, salt FROM demo_access_codes WHERE revoked_at IS NULL"
_LIST = """
    SELECT id, label, created_at, revoked_at FROM demo_access_codes ORDER BY created_at, id
"""
_REVOKE = "UPDATE demo_access_codes SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL"


@dataclass(frozen=True)
class AccessCodeInfo:
    """One code as listed: never the code itself, nor its hash."""

    id: str
    label: str
    created_at: datetime
    revoked: bool


@dataclass(frozen=True)
class NewAccessCode:
    """A freshly made code. `code` is the only time the plain code exists."""

    id: str
    label: str
    code: str


def _hash(code: str, salt: bytes) -> str:
    return hashlib.scrypt(code.encode("ascii"), salt=salt, **_SCRYPT).hex()


def _is_code(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == CODE_DIGITS and value.isascii() and value.isdigit()
    )


def _now_text() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="microseconds") + "Z"


class SqliteAccessCodeStore:
    """Create, check, list and revoke demo access codes. Safe to share between threads."""

    def __init__(self, library: SqliteLibraryStore) -> None:
        """Use the database of `library` (which has already created or upgraded it)."""
        self._library = library

    def create_code(self, label: str) -> NewAccessCode:
        """Make a random 6-digit code for `label`; returns it, once. Only its hash is stored.

        A code never repeats one that is still active. Raises ValueError if the label is
        blank, has outer whitespace or is over MAX_LABEL_LENGTH characters.
        """
        if (
            not isinstance(label, str)
            or not label
            or label != label.strip()
            or len(label) > MAX_LABEL_LENGTH
        ):
            raise ValueError(f"a label is 1 to {MAX_LABEL_LENGTH} characters, with no outer space")
        with self._library._transaction(write=True) as db:
            active = db.execute(_ACTIVE).fetchall()
            for _ in range(_MAX_NEW_CODE_TRIES):
                code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
                if not any(
                    hmac.compare_digest(_hash(code, bytes.fromhex(salt)), stored)
                    for stored, salt in active
                ):
                    break
            else:
                raise LibraryError("no free demo access code could be made")
            code_id = secrets.token_hex(4)
            salt = secrets.token_bytes(16)
            db.execute(_INSERT, (code_id, _hash(code, salt), salt.hex(), label, _now_text()))
        return NewAccessCode(id=code_id, label=label, code=code)

    def verify_code(self, code: str) -> bool:
        """Whether `code` is a 6-digit code that exists and is not revoked.

        Anything else (wrong type, wrong length, non-digits) is simply False. Every active
        code is checked with a constant-time compare, so the time does not say which matched.
        """
        if not _is_code(code):
            return False
        with self._library._transaction(write=False) as db:
            rows = db.execute(_ACTIVE).fetchall()
        matched = False
        for stored, salt in rows:
            if hmac.compare_digest(_hash(code, bytes.fromhex(salt)), stored):
                matched = True
        return matched

    def list_codes(self) -> list[AccessCodeInfo]:
        """Every code, oldest first, with its label and state; never the code or its hash."""
        with self._library._transaction(write=False) as db:
            rows = db.execute(_LIST).fetchall()
        return [
            AccessCodeInfo(
                id=row[0],
                label=row[1],
                created_at=datetime.fromisoformat(row[2]),
                revoked=row[3] is not None,
            )
            for row in rows
        ]

    def revoke_code(self, code_id: str) -> bool:
        """Revoke the code with this id. False if there is no such code or it was revoked."""
        with self._library._transaction(write=True) as db:
            return db.execute(_REVOKE, (_now_text(), code_id)).rowcount > 0
