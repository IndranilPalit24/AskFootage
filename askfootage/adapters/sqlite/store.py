"""SQLite store for the footage library: cameras, recordings, clips, zones and saved clips.

SqliteLibraryStore implements the four Protocols in askfootage/ports/library_store.py
(RecordingStore, ClipStore, ZoneStore and SavedClipStore) over one SQLite file, whose
schema is schema.sql in this package. seed_demo_data loads the demo library into it.

How the file is kept safe:
- Each operation opens its own short-lived connection, so one store can be shared by
  threads (FastAPI runs plain endpoints in a thread pool). SQLite's locking, WAL mode and
  a busy timeout put concurrent writers in turn; a connection is never shared.
- Every connection turns foreign keys on. Every write runs inside one BEGIN IMMEDIATE
  transaction, so it commits whole or not at all, and the checks it makes before writing
  cannot be raced by another writer. Multi-query reads see one consistent snapshot.
- Values only ever reach SQL as bound parameters; every statement is a fixed string.
- A refused write raises DuplicateError, MissingReferenceError or LibraryError with a
  fixed, safe message: never SQLite's own text and never the file path.

Errors the contract does not cover: a wrong Python type (a datetime where a date is
expected) raises TypeError; a value of the right type that the library cannot hold exactly
(a time with microseconds or a time zone, a note over 500 characters, a zone name over 60,
a clip whose day is not its recording's day) raises LibraryError.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime, time
from importlib import resources
from pathlib import Path

from askfootage.adapters.sqlite.seed import DemoSeed, SeedDataError, read_seed
from askfootage.ports.library_store import (
    Camera,
    Clip,
    DaySummary,
    DuplicateError,
    Evidence,
    KeyFrame,
    LibraryError,
    MissingReferenceError,
    Recording,
    SavedClip,
    Zone,
    ZonePoint,
)

SCHEMA_VERSION = 1
"""The schema version this code writes and reads; schema.sql records it in user_version."""

MAX_NOTE_LENGTH = 500
"""Longest note a saved clip may hold, in characters (as in contract/openapi.yaml)."""

MAX_ZONE_NAME_LENGTH = 60
"""Longest zone name, in characters (as in contract/openapi.yaml)."""

_MIN_SQLITE_VERSION = (3, 38, 0)  # STRICT tables need 3.37; built-in json_each needs 3.38
_BUSY_TIMEOUT_SECONDS = 10.0

# Schema changes after version 1 go here: _MIGRATIONS[n] is the SQL that takes a database
# from version n to n + 1, ending with "PRAGMA user_version = n + 1;". None exist yet.
_MIGRATIONS: dict[int, str] = {}

# --- Fixed SQL. Values are always bound as parameters, never formatted in. ------------

_CAMERAS = "SELECT id, name FROM cameras ORDER BY id"
_CAMERA_BY_ID = "SELECT id, name FROM cameras WHERE id = ?"
_ANY_CAMERA = "SELECT 1 FROM cameras LIMIT 1"
_INSERT_CAMERA = "INSERT INTO cameras (id, name) VALUES (?, ?)"

_DAY_SUMMARIES = """
    SELECT day, count(*), sum(status = 'ready')
    FROM recordings
    WHERE camera_id = ? AND day BETWEEN ? AND ?
    GROUP BY day
    ORDER BY day
"""
_RECORDINGS_ON_DAY = """
    SELECT id, camera_id, day, start_time, length_seconds, status
    FROM recordings
    WHERE camera_id = ? AND day = ?
    ORDER BY start_time, id
"""
_RECORDING_BY_ID = """
    SELECT id, camera_id, day, start_time, length_seconds, status
    FROM recordings
    WHERE id = ?
"""
_RECORDING_EXISTS = "SELECT 1 FROM recordings WHERE id = ?"
_INSERT_RECORDING = """
    INSERT INTO recordings (id, camera_id, day, start_time, length_seconds, status)
    VALUES (?, ?, ?, ?, ?, ?)
"""

_CLIPS_ON_DAY = """
    SELECT id, recording_id, day, start_time, start_seconds, end_seconds, label, zone,
           why_matched, thumbnail_url
    FROM clips
    WHERE camera_id = ? AND day = ?
    ORDER BY start_time, id
"""
_CLIP_BY_ID = """
    SELECT id, recording_id, day, start_time, start_seconds, end_seconds, label, zone,
           why_matched, thumbnail_url
    FROM clips
    WHERE id = ?
"""
_CLIP_EXISTS = "SELECT 1 FROM clips WHERE id = ?"
_EVIDENCE_OF_CLIPS = """
    SELECT clip_id, kind, text
    FROM clip_evidence
    WHERE clip_id IN (SELECT value FROM json_each(?))
    ORDER BY clip_id, position
"""
_KEY_FRAMES_OF_CLIPS = """
    SELECT clip_id, at_seconds, image_url
    FROM clip_key_frames
    WHERE clip_id IN (SELECT value FROM json_each(?))
    ORDER BY clip_id, position
"""
_INSERT_CLIP = """
    INSERT INTO clips (id, recording_id, camera_id, day, start_time, start_seconds,
                       end_seconds, label, zone, why_matched, thumbnail_url)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_INSERT_EVIDENCE = """
    INSERT INTO clip_evidence (clip_id, position, kind, text) VALUES (?, ?, ?, ?)
"""
_INSERT_KEY_FRAME = """
    INSERT INTO clip_key_frames (clip_id, position, at_seconds, image_url) VALUES (?, ?, ?, ?)
"""

_ALL_ZONES = "SELECT id, camera_id, name FROM zones ORDER BY name, id"
_ZONES_OF_CAMERA = "SELECT id, camera_id, name FROM zones WHERE camera_id = ? ORDER BY name, id"
_ZONE_BY_ID = "SELECT id, camera_id, name FROM zones WHERE id = ?"
_ZONE_CAMERA = "SELECT camera_id FROM zones WHERE id = ?"
# The names of a camera's other zones, for the name check. Names clash ignoring case by
# str.casefold, which SQLite cannot do (NOCASE folds ASCII only), so the comparison runs
# in Python, inside the write transaction, whose lock keeps other writers out meanwhile.
_OTHER_ZONE_NAMES = "SELECT name FROM zones WHERE camera_id = ? AND id <> ?"
_POINTS_OF_ZONES = """
    SELECT zone_id, x, y
    FROM zone_points
    WHERE zone_id IN (SELECT value FROM json_each(?))
    ORDER BY zone_id, position
"""
_COUNT_POINTS = "SELECT count(*) FROM zone_points WHERE zone_id = ?"
_INSERT_ZONE = "INSERT INTO zones (id, camera_id, name) VALUES (?, ?, ?)"
_INSERT_POINT = "INSERT INTO zone_points (zone_id, position, x, y) VALUES (?, ?, ?, ?)"
_RENAME_ZONE = "UPDATE zones SET name = ? WHERE id = ?"
_DELETE_POINTS = "DELETE FROM zone_points WHERE zone_id = ?"
_DELETE_ZONE = "DELETE FROM zones WHERE id = ?"

# Saved clips come back with their clip's columns after their own three. CROSS JOIN
# makes SQLite walk the (few) saved clips in saved_at order and look each clip up by
# id, instead of scanning every clip for the day filter and sorting afterwards.
_SAVED_CLIPS = """
    SELECT s.id, s.note, s.saved_at,
           c.id, c.recording_id, c.day, c.start_time, c.start_seconds, c.end_seconds,
           c.label, c.zone, c.why_matched, c.thumbnail_url
    FROM saved_clips AS s
    JOIN clips AS c ON c.id = s.clip_id
    ORDER BY s.saved_at DESC, s.id
"""
_SAVED_CLIPS_ON_DAY = """
    SELECT s.id, s.note, s.saved_at,
           c.id, c.recording_id, c.day, c.start_time, c.start_seconds, c.end_seconds,
           c.label, c.zone, c.why_matched, c.thumbnail_url
    FROM saved_clips AS s
    CROSS JOIN clips AS c ON c.id = s.clip_id
    WHERE c.day = ?
    ORDER BY s.saved_at DESC, s.id
"""
_SAVED_CLIP_BY_ID = """
    SELECT s.id, s.note, s.saved_at,
           c.id, c.recording_id, c.day, c.start_time, c.start_seconds, c.end_seconds,
           c.label, c.zone, c.why_matched, c.thumbnail_url
    FROM saved_clips AS s
    JOIN clips AS c ON c.id = s.clip_id
    WHERE s.id = ?
"""
_SAVED_ID_TAKEN = "SELECT 1 FROM saved_clips WHERE id = ?"
_CLIP_ALREADY_SAVED = "SELECT 1 FROM saved_clips WHERE clip_id = ?"
_INSERT_SAVED_CLIP = "INSERT INTO saved_clips (id, clip_id, note, saved_at) VALUES (?, ?, ?, ?)"
_UPDATE_NOTE = "UPDATE saved_clips SET note = ? WHERE id = ?"
_DELETE_SAVED_CLIP = "DELETE FROM saved_clips WHERE id = ?"


class SqliteLibraryStore:
    """The footage library in one SQLite file.

    Implements RecordingStore, ClipStore, ZoneStore and SavedClipStore from
    askfootage/ports/library_store.py, plus add_camera. Safe to share between threads.
    """

    def __init__(self, path: Path) -> None:
        """Open the library at `path`, creating its folder and schema if they are missing.

        Opening an existing library again is fine. Raises LibraryError if the file cannot
        be used: it is not a SQLite database, it holds tables AskFootage did not create, or
        it was written by a newer schema version than this code knows. Raises ValueError
        for ":memory:", since every operation opens its own connection to the file.
        """
        self._path = Path(path)
        if str(path) == ":memory:":
            raise ValueError("the library needs a file path, not ':memory:'")
        if sqlite3.sqlite_version_info < _MIN_SQLITE_VERSION:
            raise LibraryError("the library needs SQLite 3.38 or newer")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._prepare_schema()
        except sqlite3.Error:
            raise LibraryError(
                "the library database could not be opened; it may be damaged, locked "
                "or not a SQLite file"
            ) from None

    @property
    def path(self) -> Path:
        """Where the library's database file is."""
        return self._path

    # --- RecordingStore ------------------------------------------------------------

    def list_cameras(self) -> list[Camera]:
        """Every camera, ordered by id."""
        with self._transaction(write=False) as db:
            rows = db.execute(_CAMERAS).fetchall()
        return [Camera(id=row[0], name=row[1]) for row in rows]

    def get_camera(self, camera_id: str) -> Camera | None:
        """The camera with this id, or None."""
        with self._transaction(write=False) as db:
            row = db.execute(_CAMERA_BY_ID, (camera_id,)).fetchone()
        return None if row is None else Camera(id=row[0], name=row[1])

    def add_camera(self, camera: Camera) -> None:
        """Store a new camera; not part of the Protocols.

        Raises DuplicateError if the id is taken.
        """
        with self._transaction(write=True) as db:
            _insert_camera(db, camera)

    def summarise_days(self, camera_id: str, first_day: date, last_day: date) -> list[DaySummary]:
        """Recording counts per day from first_day to last_day inclusive, oldest first.

        Only days with at least one recording appear; the caller fills in empty days.
        """
        params = (camera_id, _day_text(first_day), _day_text(last_day))
        with self._transaction(write=False) as db:
            rows = db.execute(_DAY_SUMMARIES, params).fetchall()
        return [
            DaySummary(day=date.fromisoformat(row[0]), recordings=row[1], ready=row[2])
            for row in rows
        ]

    def list_recordings(self, camera_id: str, day: date) -> list[Recording]:
        """One camera's recordings on one day, ordered by start_time, then id."""
        with self._transaction(write=False) as db:
            rows = db.execute(_RECORDINGS_ON_DAY, (camera_id, _day_text(day))).fetchall()
        return [_recording_from_row(row) for row in rows]

    def get_recording(self, recording_id: str) -> Recording | None:
        """The recording with this id, or None."""
        with self._transaction(write=False) as db:
            row = db.execute(_RECORDING_BY_ID, (recording_id,)).fetchone()
        return None if row is None else _recording_from_row(row)

    def add_recording(self, recording: Recording) -> None:
        """Store a new recording.

        Raises DuplicateError if the id is taken, MissingReferenceError if the camera
        does not exist.
        """
        with self._transaction(write=True) as db:
            _insert_recording(db, recording)

    # --- ClipStore -----------------------------------------------------------------

    def list_clips(self, camera_id: str, day: date) -> list[Clip]:
        """Every clip in one camera's recordings on one day, ordered by start_time, then id."""
        with self._transaction(write=False) as db:
            rows = db.execute(_CLIPS_ON_DAY, (camera_id, _day_text(day))).fetchall()
            return _clips_from_rows(db, rows)

    def get_clip(self, clip_id: str) -> Clip | None:
        """The clip with this id, or None."""
        with self._transaction(write=False) as db:
            return _select_clip(db, clip_id)

    def add_clip(self, clip: Clip) -> None:
        """Store a new clip, keeping the order of its evidence and key frames.

        Raises DuplicateError if the id is taken, MissingReferenceError if the recording
        does not exist, LibraryError if clip.day is not the recording's day.
        """
        with self._transaction(write=True) as db:
            _insert_clip(db, clip)

    # --- ZoneStore -----------------------------------------------------------------

    def list_zones(self, camera_id: str | None = None) -> list[Zone]:
        """All zones, or only one camera's, ordered by name, then id."""
        with self._transaction(write=False) as db:
            if camera_id is None:
                rows = db.execute(_ALL_ZONES).fetchall()
            else:
                rows = db.execute(_ZONES_OF_CAMERA, (camera_id,)).fetchall()
            return _zones_from_rows(db, rows)

    def get_zone(self, zone_id: str) -> Zone | None:
        """The zone with this id, or None."""
        with self._transaction(write=False) as db:
            rows = db.execute(_ZONE_BY_ID, (zone_id,)).fetchall()
            zones = _zones_from_rows(db, rows)
        return zones[0] if zones else None

    def add_zone(self, zone: Zone) -> None:
        """Store a new zone, keeping its name's case.

        Raises DuplicateError if the id is taken or the camera already has a zone with
        this name ignoring case (str.casefold, so "Gate" and "gate" clash),
        MissingReferenceError if the camera does not exist, LibraryError if the name is
        longer than MAX_ZONE_NAME_LENGTH.
        """
        with self._transaction(write=True) as db:
            _insert_zone(db, zone)

    def replace_zone(self, zone: Zone) -> bool:
        """Replace the name and points of the zone with zone.id; its camera never changes.

        zone.camera is not read: the stored camera is kept. Returns False if there is no
        such zone. Raises DuplicateError if another zone on the same camera already has
        the new name ignoring case (renaming a zone to another case of its own name is
        fine), LibraryError if the name is longer than MAX_ZONE_NAME_LENGTH.
        """
        _check_zone_name(zone.name)
        with self._transaction(write=True) as db:
            row = db.execute(_ZONE_CAMERA, (zone.id,)).fetchone()
            if row is None:
                return False
            if _zone_name_taken(db, row[0], zone.name, zone.id):
                raise DuplicateError("this camera already has a zone with that name")
            db.execute(_RENAME_ZONE, (zone.name, zone.id))
            db.execute(_DELETE_POINTS, (zone.id,))
            _insert_points(db, zone.id, zone.points)
        return True

    def delete_zone(self, zone_id: str) -> bool:
        """Delete the zone and its points; returns False if there was no such zone."""
        with self._transaction(write=True) as db:
            return db.execute(_DELETE_ZONE, (zone_id,)).rowcount > 0

    # --- SavedClipStore ------------------------------------------------------------

    def list_saved_clips(self, day: date | None = None) -> list[SavedClip]:
        """Saved clips, newest saved_at first, then id; only clips from `day` if given."""
        with self._transaction(write=False) as db:
            if day is None:
                rows = db.execute(_SAVED_CLIPS).fetchall()
            else:
                rows = db.execute(_SAVED_CLIPS_ON_DAY, (_day_text(day),)).fetchall()
            return _saved_clips_from_rows(db, rows)

    def get_saved_clip(self, saved_id: str) -> SavedClip | None:
        """The saved clip with this id, or None."""
        with self._transaction(write=False) as db:
            return _select_saved_clip(db, saved_id)

    def add_saved_clip(
        self, saved_id: str, clip_id: str, note: str, saved_at: datetime
    ) -> SavedClip:
        """Save a clip with a note and return the saved clip, its saved_at in UTC.

        Raises MissingReferenceError if the clip does not exist, DuplicateError if the
        id is taken or the clip is already saved, LibraryError if the note is longer
        than MAX_NOTE_LENGTH, ValueError for a bad id or a naive saved_at.
        """
        with self._transaction(write=True) as db:
            return _insert_saved_clip(db, saved_id, clip_id, note, saved_at)

    def update_note(self, saved_id: str, note: str) -> SavedClip | None:
        """Change the note; returns the saved clip after the change, or None if unknown.

        Raises LibraryError if the note is longer than MAX_NOTE_LENGTH.
        """
        _check_note(note)
        with self._transaction(write=True) as db:
            if db.execute(_UPDATE_NOTE, (note, saved_id)).rowcount == 0:
                return None
            return _select_saved_clip(db, saved_id)

    def delete_saved_clip(self, saved_id: str) -> bool:
        """Remove a saved clip (the clip itself stays); returns False if it was not saved."""
        with self._transaction(write=True) as db:
            return db.execute(_DELETE_SAVED_CLIP, (saved_id,)).rowcount > 0

    # --- Seeding -------------------------------------------------------------------

    def _add_all_if_empty(self, seed: DemoSeed) -> bool:
        """Write a whole seed in one transaction, unless the library already has a camera."""
        with self._transaction(write=True) as db:
            if _found(db, _ANY_CAMERA, ()):
                return False
            for camera in seed.cameras:
                _insert_camera(db, camera)
            for recording in seed.recordings:
                _insert_recording(db, recording)
            for clip in seed.clips:
                _insert_clip(db, clip)
            for zone in seed.zones:
                _insert_zone(db, zone)
            for saved in seed.saved_clips:
                _insert_saved_clip(db, saved.id, saved.clip_id, saved.note, saved.saved_at)
        return True

    # --- Connections and transactions ----------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        # autocommit=True: the driver opens no transactions of its own; _transaction does.
        connection = sqlite3.connect(self._path, timeout=_BUSY_TIMEOUT_SECONDS, autocommit=True)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
        except BaseException:
            connection.close()
            raise
        return connection

    @contextmanager
    def _transaction(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        """A fresh connection inside one transaction, closed afterwards.

        The transaction commits if the block finishes and rolls back if it raises. A write
        takes SQLite's write lock up front (IMMEDIATE), so its checks cannot be raced.
        """
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN DEFERRED")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        except sqlite3.IntegrityError as error:
            raise _refusal(error) from None
        except OverflowError:
            raise LibraryError("a number is too large for the library to store") from None
        finally:
            connection.close()

    def _prepare_schema(self) -> None:
        """Create the schema in a new database, or check the version of an existing one."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    if _found(connection, "SELECT 1 FROM sqlite_schema LIMIT 1", ()):
                        raise LibraryError(
                            "the database file holds tables AskFootage did not create"
                        )
                    connection.executescript(_schema_sql())
                elif version > SCHEMA_VERSION:
                    raise LibraryError(
                        f"the library database uses schema version {version}, newer than "
                        f"this AskFootage reads ({SCHEMA_VERSION}); update AskFootage"
                    )
                else:
                    for step in range(version, SCHEMA_VERSION):
                        connection.executescript(_MIGRATIONS[step])
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            # WAL lets readers and one writer work at once. The setting is stored in the
            # file; it is only an optimisation, so a file system that refuses it is fine.
            try:
                connection.execute("PRAGMA journal_mode = WAL")
            except sqlite3.OperationalError:
                pass
        finally:
            connection.close()


def seed_demo_data(store: SqliteLibraryStore, seed_file: Path) -> bool:
    """Load the demo library from seed_file into an empty database, in one transaction.

    Returns True if it seeded. Returns False, changing nothing, when the database already
    holds any camera, so restarting the app never brings back zones the user deleted or
    duplicates rows. Raises SeedDataError, leaving the database as it was, if the file is
    malformed or its rows break the library's rules (a repeated id, a clip pointing at a
    recording that is not in the seed); OSError if the file cannot be read.
    """
    seed = read_seed(seed_file)
    try:
        return store._add_all_if_empty(seed)
    except (LibraryError, ValueError) as error:
        raise SeedDataError(f"demo seed rows were refused: {error}") from None


# --- Writes shared by the public methods and the seed (one connection, caller's tx) ---


def _insert_camera(db: sqlite3.Connection, camera: Camera) -> None:
    if _found(db, _CAMERA_BY_ID, (camera.id,)):
        raise DuplicateError("a camera with this id already exists")
    db.execute(_INSERT_CAMERA, (camera.id, camera.name))


def _insert_recording(db: sqlite3.Connection, recording: Recording) -> None:
    values = (
        recording.id,
        recording.camera,
        _day_text(recording.day),
        _seconds_of_day(recording.start_time),
        recording.length_seconds,
        recording.status,
    )
    if not _found(db, _CAMERA_BY_ID, (recording.camera,)):
        raise MissingReferenceError("there is no camera with this id")
    if _found(db, _RECORDING_EXISTS, (recording.id,)):
        raise DuplicateError("a recording with this id already exists")
    db.execute(_INSERT_RECORDING, values)


def _insert_clip(db: sqlite3.Connection, clip: Clip) -> None:
    day = _day_text(clip.day)
    start_time = _seconds_of_day(clip.start_time)
    recording = db.execute(_RECORDING_BY_ID, (clip.recording_id,)).fetchone()
    if recording is None:
        raise MissingReferenceError("there is no recording with this id")
    camera_id, recording_day = recording[1], recording[2]
    if recording_day != day:
        raise LibraryError("a clip's day must be the day of its recording")
    if _found(db, _CLIP_EXISTS, (clip.id,)):
        raise DuplicateError("a clip with this id already exists")
    db.execute(
        _INSERT_CLIP,
        (
            clip.id,
            clip.recording_id,
            camera_id,
            day,
            start_time,
            clip.start_seconds,
            clip.end_seconds,
            clip.label,
            clip.zone,
            clip.why_matched,
            clip.thumbnail_url,
        ),
    )
    db.executemany(
        _INSERT_EVIDENCE,
        [(clip.id, position, item.kind, item.text) for position, item in enumerate(clip.evidence)],
    )
    db.executemany(
        _INSERT_KEY_FRAME,
        [
            (clip.id, position, frame.at_seconds, frame.image_url)
            for position, frame in enumerate(clip.key_frames)
        ],
    )


def _insert_zone(db: sqlite3.Connection, zone: Zone) -> None:
    _check_zone_name(zone.name)
    if not _found(db, _CAMERA_BY_ID, (zone.camera,)):
        raise MissingReferenceError("there is no camera with this id")
    if _found(db, _ZONE_CAMERA, (zone.id,)):
        raise DuplicateError("a zone with this id already exists")
    if _zone_name_taken(db, zone.camera, zone.name, zone.id):
        raise DuplicateError("this camera already has a zone with that name")
    db.execute(_INSERT_ZONE, (zone.id, zone.camera, zone.name))
    _insert_points(db, zone.id, zone.points)


def _zone_name_taken(db: sqlite3.Connection, camera_id: str, name: str, zone_id: str) -> bool:
    """Whether a zone on the camera other than zone_id has this name, ignoring case.

    Call it only inside a write transaction: the write lock it holds is what stops another
    writer adding a clashing name between this check and the caller's write. The schema's
    UNIQUE (camera_id, name) index still refuses an exact repeat from any writer.
    """
    wanted = name.casefold()
    return any(
        other.casefold() == wanted
        for (other,) in db.execute(_OTHER_ZONE_NAMES, (camera_id, zone_id))
    )


def _insert_points(db: sqlite3.Connection, zone_id: str, points: Sequence[ZonePoint]) -> None:
    db.executemany(
        _INSERT_POINT,
        [(zone_id, position, float(x), float(y)) for position, (x, y) in enumerate(points)],
    )
    # The schema cannot count rows in a CHECK; this runs in the same transaction, so a
    # zone left with fewer than 3 points is rolled back with everything else.
    if db.execute(_COUNT_POINTS, (zone_id,)).fetchone()[0] < 3:
        raise LibraryError("a zone needs at least 3 points")


def _insert_saved_clip(
    db: sqlite3.Connection, saved_id: str, clip_id: str, note: str, saved_at: datetime
) -> SavedClip:
    clip = _select_clip(db, clip_id)
    if clip is None:
        raise MissingReferenceError("there is no clip with this id")
    saved = SavedClip(id=saved_id, clip=clip, note=note, saved_at=saved_at)  # validates
    _check_note(note)
    saved_at_text = _utc_text(saved.saved_at)
    if _found(db, _SAVED_ID_TAKEN, (saved_id,)):
        raise DuplicateError("a saved clip with this id already exists")
    if _found(db, _CLIP_ALREADY_SAVED, (clip_id,)):
        raise DuplicateError("this clip is already saved")
    db.execute(_INSERT_SAVED_CLIP, (saved_id, clip_id, note, saved_at_text))
    return SavedClip(id=saved_id, clip=clip, note=note, saved_at=_utc_datetime(saved_at_text))


# --- Reads -----------------------------------------------------------------------------


def _select_clip(db: sqlite3.Connection, clip_id: str) -> Clip | None:
    clips = _clips_from_rows(db, db.execute(_CLIP_BY_ID, (clip_id,)).fetchall())
    return clips[0] if clips else None


def _select_saved_clip(db: sqlite3.Connection, saved_id: str) -> SavedClip | None:
    saved = _saved_clips_from_rows(db, db.execute(_SAVED_CLIP_BY_ID, (saved_id,)).fetchall())
    return saved[0] if saved else None


def _clips_from_rows(db: sqlite3.Connection, rows: Sequence[Sequence[object]]) -> list[Clip]:
    """Clips for rows in _CLIP_BY_ID's column order, with their evidence and key frames."""
    if not rows:
        return []
    ids = json.dumps([row[0] for row in rows])
    evidence: defaultdict[str, list[Evidence]] = defaultdict(list)
    for clip_id, kind, text in db.execute(_EVIDENCE_OF_CLIPS, (ids,)):
        evidence[clip_id].append(Evidence(kind=kind, text=text))
    key_frames: defaultdict[str, list[KeyFrame]] = defaultdict(list)
    for clip_id, at_seconds, image_url in db.execute(_KEY_FRAMES_OF_CLIPS, (ids,)):
        key_frames[clip_id].append(KeyFrame(at_seconds=at_seconds, image_url=image_url))
    return [
        Clip(
            id=row[0],
            recording_id=row[1],
            day=date.fromisoformat(row[2]),
            start_time=_time_of_day(row[3]),
            start_seconds=row[4],
            end_seconds=row[5],
            label=row[6],
            evidence=tuple(evidence[row[0]]),
            zone=row[7],
            why_matched=row[8],
            key_frames=tuple(key_frames[row[0]]),
            thumbnail_url=row[9],
        )
        for row in rows
    ]


def _zones_from_rows(db: sqlite3.Connection, rows: Sequence[Sequence[object]]) -> list[Zone]:
    """Zones for (id, camera_id, name) rows, with their points in order."""
    if not rows:
        return []
    points: defaultdict[str, list[ZonePoint]] = defaultdict(list)
    for zone_id, x, y in db.execute(_POINTS_OF_ZONES, (json.dumps([row[0] for row in rows]),)):
        points[zone_id].append((x, y))
    return [
        Zone(id=row[0], camera=row[1], name=row[2], points=tuple(points[row[0]])) for row in rows
    ]


def _saved_clips_from_rows(
    db: sqlite3.Connection, rows: Sequence[Sequence[object]]
) -> list[SavedClip]:
    """Saved clips for rows in _SAVED_CLIPS' column order."""
    clips = {clip.id: clip for clip in _clips_from_rows(db, [row[3:] for row in rows])}
    return [
        SavedClip(id=row[0], clip=clips[row[3]], note=row[1], saved_at=_utc_datetime(row[2]))
        for row in rows
    ]


def _recording_from_row(row: Sequence[object]) -> Recording:
    return Recording(
        id=row[0],
        camera=row[1],
        day=date.fromisoformat(row[2]),
        start_time=_time_of_day(row[3]),
        length_seconds=row[4],
        status=row[5],
    )


# --- Small helpers -----------------------------------------------------------------------


def _found(db: sqlite3.Connection, sql: str, params: Sequence[object]) -> bool:
    return db.execute(sql, params).fetchone() is not None


def _refusal(error: sqlite3.IntegrityError) -> LibraryError:
    """The library error for a constraint SQLite enforced, without SQLite's own message."""
    name = getattr(error, "sqlite_errorname", "")
    if name in ("SQLITE_CONSTRAINT_PRIMARYKEY", "SQLITE_CONSTRAINT_UNIQUE"):
        return DuplicateError("an item with this id or name already exists")
    if name == "SQLITE_CONSTRAINT_FOREIGNKEY":
        return MissingReferenceError("the camera, recording or clip it refers to does not exist")
    return LibraryError("the library refused a value that breaks its rules")


def _check_note(note: str) -> None:
    if len(note) > MAX_NOTE_LENGTH:
        raise LibraryError(f"a note can be at most {MAX_NOTE_LENGTH} characters")


def _check_zone_name(name: str) -> None:
    if len(name) > MAX_ZONE_NAME_LENGTH:
        raise LibraryError(f"a zone name can be at most {MAX_ZONE_NAME_LENGTH} characters")


def _day_text(day: date) -> str:
    if isinstance(day, datetime) or not isinstance(day, date):
        raise TypeError("a day must be a datetime.date (not a datetime)")
    return day.isoformat()


def _seconds_of_day(value: time) -> int:
    if not isinstance(value, time):
        raise TypeError("a time of day must be a datetime.time")
    if value.tzinfo is not None or value.microsecond:
        raise LibraryError("a time of day must be a camera-local time in whole seconds")
    return value.hour * 3600 + value.minute * 60 + value.second


def _time_of_day(seconds: int) -> time:
    return time(seconds // 3600, seconds // 60 % 60, seconds % 60)


def _utc_text(moment: datetime) -> str:
    """'YYYY-MM-DDTHH:MM:SS.ffffffZ': fixed width, so text order is time order."""
    return moment.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="microseconds") + "Z"


def _utc_datetime(text: str) -> datetime:
    return datetime.fromisoformat(text)  # the trailing Z makes it aware, in UTC


def _schema_sql() -> str:
    schema = resources.files("askfootage.adapters.sqlite").joinpath("schema.sql")
    return schema.read_text(encoding="utf-8")
