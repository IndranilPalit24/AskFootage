"""A deterministic demo volume: invented cameras, zones and recordings, and no activity.

The two real clips (and the demo seed) show the product working, but one or three cameras do
not show what a factory-sized library looks like. This module invents the rest of the
library: 18 cameras with factory-style names, their zones, and seven days of recordings each,
ending on the demo day. It invents nothing that would pass for evidence: no tracks, no clips,
no saved clips, no search matches, proofs or snapshots. Its recordings have no video file
(Recording.has_footage is False), and most are "ready" only in the sense that the library
lists them as searchable-in-principle.

Two halves:
- generate_volume() is pure: the same arguments give the same rows, byte for byte, on every
  run. It uses its own small random generator (SplitMix64) instead of the random module, so
  the output does not depend on the Python version. Standard library only, no network.
- add_volume(), remove_volume() and volume_status() put the rows into a SqliteLibraryStore,
  every one tagged origin 'demo_volume', and take them out again. Real rows are never
  changed. add_volume twice changes nothing the second time; remove_volume leaves the
  database as it was before add_volume (every row of every table, and the camera counter),
  except that a database file keeps whatever free pages SQLite does not give back.

No name here is a real company, person or product, and there is no model or vendor name.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from askfootage.adapters.sqlite.store import (
    SqliteLibraryStore,
    _insert_camera,
    _insert_recording,
    _insert_zone,
)
from askfootage.ports.library_store import (
    Camera,
    CameraStatus,
    LibraryError,
    Recording,
    RecordingStatus,
    Zone,
    ZonePoint,
    camera_id_for,
)

VOLUME_ORIGIN = "demo_volume"
"""The origin tag on every generated row."""

REAL_ORIGIN = "real"
"""The origin of every other row."""

VOLUME_SEED = 20261030
"""The fixed seed: the same volume on every run."""

DEMO_DAY = date(2026, 10, 30)
"""The last day of the volume: the demo dataset's "today" (contract/examples/demo-seed.json)."""

VOLUME_DAYS = 7
"""Days of recordings per camera, ending on the demo day (the days the day picker shows)."""

USERNAME = "viewer"
"""The stream login every generated camera lists (a login name, not a person)."""

_SAVED_CLIP_REFUSAL = (
    "the demo volume cannot be removed: a saved clip points at one of its recordings; "
    "delete that saved clip first"
)
_ATTACHED_REFUSAL = (
    "the demo volume cannot be removed: real recordings or zones were added to one of its "
    "cameras; delete or move them first"
)

# Why a recording failed to index: plain sentences for the person looking at the list.
_FAILURE_NOTES = (
    "Indexing failed. Try again.",
    "The video file could not be read. Add the recording again.",
    "Preparing the video ran out of disk space. Free some space and try again.",
    "The recording ended before it could be prepared. Try again.",
)

_MASK = (1 << 64) - 1


class _Rng:
    """SplitMix64: a tiny, fixed random generator, so output never depends on Python."""

    def __init__(self, seed: int) -> None:
        self._state = seed & _MASK

    def next(self) -> int:
        """The next 64-bit number."""
        self._state = (self._state + 0x9E3779B97F4A7C15) & _MASK
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
        return z ^ (z >> 31)

    def below(self, limit: int) -> int:
        """A whole number from 0 up to, not including, limit."""
        return self.next() % limit

    def between(self, low: int, high: int) -> int:
        """A whole number from low to high, both included."""
        return low + self.below(high - low + 1)


@dataclass(frozen=True, slots=True)
class _CameraSpec:
    name: str
    location: str
    department: str
    status: CameraStatus
    zone_names: tuple[str, ...]  # candidates; a camera takes the first 2 to 5 of them
    shift: tuple[int, int]  # recording hours on a weekday: first hour, end hour
    always_on: bool = False  # still records on a Sunday
    days_recorded: int = VOLUME_DAYS  # a standby or offline camera stopped recording earlier


_SPECS: tuple[_CameraSpec, ...] = (
    _CameraSpec(
        "Loading Bay 1",
        "Dock row A, bay 1",
        "Outbound Flow",
        "online",
        ("Bay door", "Pallet staging", "Forklift lane", "Dock edge", "Walkway"),
        (6, 20),
    ),
    _CameraSpec(
        "Loading Bay 2",
        "Dock row A, bay 2",
        "Outbound Flow",
        "online",
        ("Bay door", "Pallet staging", "Trailer apron", "Forklift lane", "Walkway"),
        (6, 20),
    ),
    _CameraSpec(
        "Packaging Line A",
        "Hall 2, line A",
        "Pack and Seal",
        "online",
        ("Infeed belt", "Sealing station", "Outfeed table", "Box stack", "Operator walkway"),
        (6, 22),
    ),
    _CameraSpec(
        "Packaging Line B",
        "Hall 2, line B",
        "Pack and Seal",
        "online",
        ("Infeed belt", "Labelling station", "Outfeed table", "Box stack", "Operator walkway"),
        (6, 22),
    ),
    _CameraSpec(
        "Exit Lane East",
        "East exit corridor",
        "Site Services",
        "online",
        ("Exit lane", "Door frame", "Waiting line", "Floor marking", "Side corridor"),
        (6, 20),
    ),
    _CameraSpec(
        "Yard Gate North",
        "North yard entrance",
        "Yard Control",
        "online",
        ("Gate lane", "Barrier arm", "Weighbridge", "Queue area", "Pedestrian path"),
        (5, 23),
        always_on=True,
    ),
    _CameraSpec(
        "Yard Gate South",
        "South yard entrance",
        "Yard Control",
        "online",
        ("Gate lane", "Barrier arm", "Queue area", "Visitor bay", "Pedestrian path"),
        (5, 23),
        always_on=True,
    ),
    _CameraSpec(
        "Dispatch Door 1",
        "Dispatch hall, door 1",
        "Outbound Flow",
        "online",
        ("Roller door", "Parcel cage", "Scan point", "Van bay", "Walkway"),
        (7, 19),
    ),
    _CameraSpec(
        "Dispatch Door 2",
        "Dispatch hall, door 2",
        "Outbound Flow",
        "online",
        ("Roller door", "Parcel cage", "Scan point", "Van bay", "Walkway"),
        (7, 19),
    ),
    _CameraSpec(
        "Warehouse Aisle 4",
        "Warehouse, aisle 4",
        "Stock Control",
        "online",
        ("Rack front", "Aisle centre", "Pick bay", "Cross aisle", "Ladder point"),
        (6, 20),
    ),
    _CameraSpec(
        "Warehouse Aisle 7",
        "Warehouse, aisle 7",
        "Stock Control",
        "online",
        ("Rack front", "Aisle centre", "Pick bay", "Cross aisle", "Ladder point"),
        (6, 20),
    ),
    _CameraSpec(
        "Goods-In Dock",
        "Receiving hall, dock 3",
        "Goods Receipt",
        "online",
        ("Unloading door", "Check table", "Pallet wrap", "Forklift lane", "Waiting area"),
        (6, 18),
    ),
    _CameraSpec(
        "Goods-In Inspection",
        "Receiving hall, bench",
        "Goods Receipt",
        "offline",
        ("Check table", "Quarantine rack", "Scale", "Waiting area", "Walkway"),
        (6, 18),
        days_recorded=3,
    ),
    _CameraSpec(
        "Maintenance Bay",
        "Workshop, bay 1",
        "Plant Care",
        "online",
        ("Workbench", "Tool wall", "Lift area", "Parts cage", "Walkway"),
        (7, 17),
    ),
    _CameraSpec(
        "Staff Entrance",
        "West side door",
        "Site Services",
        "online",
        ("Door frame", "Badge reader", "Lobby floor", "Locker corridor", "Stairs"),
        (5, 21),
        always_on=True,
    ),
    _CameraSpec(
        "Pallet Store",
        "Outside store, row C",
        "Stock Control",
        "standby",
        ("Row entrance", "Stack zone", "Forklift lane", "Fence line", "Walkway"),
        (7, 17),
        days_recorded=5,
    ),
    _CameraSpec(
        "Charging Area",
        "Hall 1, charging corner",
        "Plant Care",
        "standby",
        (),  # no zones drawn yet
        (7, 17),
        days_recorded=5,
    ),
    _CameraSpec(
        "Waste Compound",
        "Rear compound",
        "Site Services",
        "offline",
        (),  # no zones drawn yet
        (7, 17),
        days_recorded=3,
    ),
)

CAMERA_COUNT = len(_SPECS)
"""How many cameras the volume adds."""

_GRID_COLUMNS = 3
_GRID_ROWS = 2


@dataclass(frozen=True, slots=True)
class VolumeData:
    """Every row of the volume, in the order they are written."""

    cameras: tuple[Camera, ...]
    zones: tuple[Zone, ...]
    recordings: tuple[Recording, ...]


def generate_volume(
    first_camera_number: int,
    *,
    last_day: date = DEMO_DAY,
    taken_camera_names: Collection[str] = (),
) -> VolumeData:
    """The volume's rows, numbered from CAM-<first_camera_number> upward.

    Pure and deterministic: the same arguments always give the same rows. A camera name that
    clashes (ignoring case) with one in taken_camera_names gets " (2)" added, so the volume
    can be added next to cameras someone named by hand.
    """
    if first_camera_number < 1:
        raise ValueError("camera numbers start at 1")
    taken = {name.casefold() for name in taken_camera_names}
    cameras: list[Camera] = []
    zones: list[Zone] = []
    recordings: list[Recording] = []
    first_day = last_day - timedelta(days=VOLUME_DAYS - 1)
    for index, spec in enumerate(_SPECS):
        number = first_camera_number + index
        camera_id = camera_id_for(number)
        name = _free_name(spec.name, taken)
        taken.add(name.casefold())
        cameras.append(
            Camera(
                id=camera_id,
                name=name,
                ip=f"198.51.100.{20 + index}",  # documentation range: no real host
                username=USERNAME,
                status=spec.status,
                location=spec.location,
                department=spec.department,
                created_at=datetime(2026, 10, 20, 7, 30, tzinfo=UTC) + timedelta(minutes=5 * index),
            )
        )
        rng = _Rng(VOLUME_SEED ^ ((index + 1) * 0x9E3779B97F4A7C15))
        zones.extend(_zones_for(camera_id, number, spec, rng))
        recordings.extend(_recordings_for(camera_id, number, spec, first_day, last_day, rng))
    return VolumeData(tuple(cameras), tuple(zones), tuple(recordings))


def _free_name(name: str, taken: set[str]) -> str:
    candidate, copy = name, 1
    while candidate.casefold() in taken:
        copy += 1
        candidate = f"{name} ({copy})"
    return candidate


def _zones_for(camera_id: str, number: int, spec: _CameraSpec, rng: _Rng) -> list[Zone]:
    if not spec.zone_names:
        return []
    count = min(len(spec.zone_names), 2 + rng.below(4))  # 2 to 5
    cells = list(range(_GRID_COLUMNS * _GRID_ROWS))
    for i in range(len(cells) - 1, 0, -1):  # Fisher-Yates shuffle
        j = rng.below(i + 1)
        cells[i], cells[j] = cells[j], cells[i]
    return [
        Zone(
            id=f"vz-{number:03d}-{position + 1}",
            camera=camera_id,
            name=spec.zone_names[position],
            points=_quad_in_cell(cells[position], rng),
        )
        for position in range(count)
    ]


def _quad_in_cell(cell: int, rng: _Rng) -> tuple[ZonePoint, ...]:
    """A convex four-sided shape, clockwise from the top left, inside one grid cell.

    Each zone has its own cell, so a camera's zones never overlap. Corners sit 0.02 to 0.09
    inside the cell and are pulled in by up to 0.04 more, so the shape is never a flat line
    and its area is well above zero.
    """
    column, row = cell % _GRID_COLUMNS, cell // _GRID_COLUMNS
    left, right = column / _GRID_COLUMNS, (column + 1) / _GRID_COLUMNS
    top, bottom = row / _GRID_ROWS, (row + 1) / _GRID_ROWS

    def margin() -> float:
        return (20 + rng.below(71)) / 1000  # 0.020 to 0.090

    def pull() -> float:
        return rng.below(41) / 1000  # 0.000 to 0.040

    x0, x1, y0, y1 = left + margin(), right - margin(), top + margin(), bottom - margin()
    corners = (
        (x0 + pull(), y0 + pull()),
        (x1 - pull(), y0 + pull()),
        (x1 - pull(), y1 - pull()),
        (x0 + pull(), y1 - pull()),
    )
    return tuple((round(x, 3), round(y, 3)) for x, y in corners)


def _recordings_for(
    camera_id: str, number: int, spec: _CameraSpec, first_day: date, last_day: date, rng: _Rng
) -> list[Recording]:
    found: list[Recording] = []
    for offset in range(spec.days_recorded):
        day = first_day + timedelta(days=offset)
        shift = _shift_on(spec, day)
        if shift is None:
            continue
        cursor = shift[0] * 3600 + rng.below(16) * 60
        while True:
            length = rng.between(15, 60) * 60  # 15 to 60 minutes
            if cursor + length > shift[1] * 3600:
                break
            status, note = _status_of(day == last_day, rng)
            found.append(
                Recording(
                    id=f"vr-{number:03d}-{day:%Y%m%d}-{cursor // 3600:02d}{cursor // 60 % 60:02d}",
                    camera=camera_id,
                    day=day,
                    start_time=time(cursor // 3600, cursor // 60 % 60),
                    length_seconds=length,
                    status=status,
                    status_note=note,
                    has_footage=False,
                )
            )
            cursor += length + rng.between(0, 30) * 60  # a gap of up to 30 minutes
    return found


def _shift_on(spec: _CameraSpec, day: date) -> tuple[int, int] | None:
    """The hours a camera records on a day, or None when it does not record."""
    weekday = day.weekday()
    if weekday == 6:  # Sunday: only the entrances
        return (8, 20) if spec.always_on else None
    if weekday == 5:  # Saturday: shorter shift
        start, end = spec.shift
        return (start + 1, min(end, 15))
    return spec.shift


def _status_of(is_last_day: bool, rng: _Rng) -> tuple[RecordingStatus, str | None]:
    """Mostly ready; a few still being processed (the newest day only) and a few failed."""
    roll = rng.below(1000)
    if roll < 9:
        return "waiting", _FAILURE_NOTES[rng.below(len(_FAILURE_NOTES))]
    if is_last_day and roll < 55:
        return ("preparing" if roll % 2 else "indexing"), None
    return "ready", None


# --- Writing the volume to a library --------------------------------------------------------

_LAST_CAMERA_NUMBER = "SELECT last_number FROM camera_sequence WHERE only_row = 1"
_VOLUME_CAMERA_COUNT = "SELECT count(*) FROM cameras WHERE origin = 'demo_volume'"
_VOLUME_STATE_ROW = "SELECT prior_last_camera_number FROM volume_state WHERE only_row = 1"
_NAMES = "SELECT name FROM cameras"
_SAVE_PRIOR = "INSERT INTO volume_state (only_row, prior_last_camera_number) VALUES (1, ?)"
_FORGET_PRIOR = "DELETE FROM volume_state WHERE only_row = 1"
_REAL_ON_VOLUME_CAMERAS = """
    SELECT (SELECT count(*) FROM recordings
            WHERE origin <> 'demo_volume'
              AND camera_id IN (SELECT id FROM cameras WHERE origin = 'demo_volume'))
         + (SELECT count(*) FROM zones
            WHERE origin <> 'demo_volume'
              AND camera_id IN (SELECT id FROM cameras WHERE origin = 'demo_volume'))
"""
_SAVED_ON_VOLUME = """
    SELECT count(*) FROM saved_clips AS s
    JOIN clips AS c ON c.id = s.clip_id
    JOIN recordings AS r ON r.id = c.recording_id
    WHERE r.origin = 'demo_volume'
"""
_DELETE_VOLUME_RECORDINGS = "DELETE FROM recordings WHERE origin = 'demo_volume'"
_DELETE_VOLUME_ZONES = "DELETE FROM zones WHERE origin = 'demo_volume'"
_DELETE_VOLUME_CAMERAS = "DELETE FROM cameras WHERE origin = 'demo_volume'"
_HIGHEST_CAMERA_NUMBER = "SELECT coalesce(max(number), 0) FROM cameras"
_SET_COUNTER = "UPDATE camera_sequence SET last_number = ? WHERE only_row = 1"
_COUNTER_GUARD = """
    SELECT sql FROM sqlite_schema
    WHERE type = 'trigger' AND name = 'camera_sequence_never_goes_back'
"""
_DROP_COUNTER_GUARD = "DROP TRIGGER camera_sequence_never_goes_back"

# Rows per table, split by origin. Tables without an origin column of their own are counted
# through the row they hang from, so "no generated tracks or clips" is a measured fact.
_STATUS_QUERIES: tuple[tuple[str, str], ...] = (
    ("cameras", "SELECT origin, count(*) FROM cameras GROUP BY origin"),
    ("zones", "SELECT origin, count(*) FROM zones GROUP BY origin"),
    (
        "zone_points",
        "SELECT z.origin, count(*) FROM zone_points AS p JOIN zones AS z ON z.id = p.zone_id "
        "GROUP BY z.origin",
    ),
    ("recordings", "SELECT origin, count(*) FROM recordings GROUP BY origin"),
    (
        "clips",
        "SELECT r.origin, count(*) FROM clips AS c JOIN recordings AS r ON r.id = c.recording_id "
        "GROUP BY r.origin",
    ),
    (
        "clip_evidence",
        "SELECT r.origin, count(*) FROM clip_evidence AS e JOIN clips AS c ON c.id = e.clip_id "
        "JOIN recordings AS r ON r.id = c.recording_id GROUP BY r.origin",
    ),
    (
        "clip_key_frames",
        "SELECT r.origin, count(*) FROM clip_key_frames AS k JOIN clips AS c ON c.id = k.clip_id "
        "JOIN recordings AS r ON r.id = c.recording_id GROUP BY r.origin",
    ),
    (
        "saved_clips",
        "SELECT r.origin, count(*) FROM saved_clips AS s JOIN clips AS c ON c.id = s.clip_id "
        "JOIN recordings AS r ON r.id = c.recording_id GROUP BY r.origin",
    ),
    (
        "tracks",
        "SELECT r.origin, count(*) FROM tracks AS t JOIN recordings AS r ON r.id = t.recording_id "
        "GROUP BY r.origin",
    ),
    (
        "track_points",
        "SELECT r.origin, count(*) FROM track_points AS p JOIN tracks AS t ON t.id = p.track_row "
        "JOIN recordings AS r ON r.id = t.recording_id GROUP BY r.origin",
    ),
    (
        "concepts_searched",
        "SELECT r.origin, count(*) FROM concepts_searched AS m "
        "JOIN recordings AS r ON r.id = m.recording_id GROUP BY r.origin",
    ),
)


def add_volume(store: SqliteLibraryStore) -> bool:
    """Add the volume to the library in one transaction; True if it added, False if present.

    Idempotent: when any volume camera is already there, nothing is written. The cameras take
    the numbers after the camera counter, so they never reuse an id. Real rows are not read
    except for their camera names, and not changed. A failure rolls everything back.
    """
    with store._transaction(write=True) as db:
        if (
            db.execute(_VOLUME_CAMERA_COUNT).fetchone()[0]
            or db.execute(_VOLUME_STATE_ROW).fetchone()
        ):
            return False
        last = db.execute(_LAST_CAMERA_NUMBER).fetchone()[0]
        names = [name for (name,) in db.execute(_NAMES)]
        data = generate_volume(last + 1, taken_camera_names=names)
        db.execute(_SAVE_PRIOR, (last,))
        for camera in data.cameras:
            _insert_camera(db, camera, VOLUME_ORIGIN)
        for zone in data.zones:
            _insert_zone(db, zone, VOLUME_ORIGIN)
        for recording in data.recordings:
            _insert_recording(db, recording, VOLUME_ORIGIN)
    return True


def remove_volume(store: SqliteLibraryStore) -> int:
    """Delete every origin 'demo_volume' row and restore the camera counter; returns the
    number of cameras removed (0 when there was no volume, and nothing changes).

    Raises LibraryError, changing nothing, if a real recording or zone was added to a volume
    camera or a clip was saved from a volume recording: removing the volume would delete
    someone's work. Anything else hanging from a volume row (clips, tracks and markers a
    pass derived from it) goes with it.
    """
    with store._transaction(write=True) as db:
        cameras = db.execute(_VOLUME_CAMERA_COUNT).fetchone()[0]
        prior = db.execute(_VOLUME_STATE_ROW).fetchone()
        if not cameras and prior is None:
            return 0
        if db.execute(_REAL_ON_VOLUME_CAMERAS).fetchone()[0]:
            raise LibraryError(_ATTACHED_REFUSAL)
        if db.execute(_SAVED_ON_VOLUME).fetchone()[0]:
            raise LibraryError(_SAVED_CLIP_REFUSAL)
        db.execute(_DELETE_VOLUME_RECORDINGS)
        db.execute(_DELETE_VOLUME_ZONES)
        db.execute(_DELETE_VOLUME_CAMERAS)
        if prior is not None:
            # The counter may only go up, by a trigger; lift that rule for this one reset
            # and put the very same trigger back. DDL is transactional in SQLite, so a
            # failure anywhere rolls the trigger back too. Never below a remaining camera.
            guard = db.execute(_COUNTER_GUARD).fetchone()[0]
            db.execute(_DROP_COUNTER_GUARD)
            highest = db.execute(_HIGHEST_CAMERA_NUMBER).fetchone()[0]
            db.execute(_SET_COUNTER, (max(prior[0], highest),))
            db.execute(guard)
            db.execute(_FORGET_PRIOR)
    return cameras


def volume_status(store: SqliteLibraryStore) -> dict[str, dict[str, int]]:
    """Row counts per table and origin: {table: {'real': n, 'demo_volume': m}}.

    Every table that can hold rows from the volume is listed; a count of 0 is shown as 0.
    Tables without their own origin column are counted through the recording, camera or zone
    they belong to.
    """
    status: dict[str, dict[str, int]] = {}
    with store._transaction(write=False) as db:
        for table, query in _STATUS_QUERIES:
            counts = {REAL_ORIGIN: 0, VOLUME_ORIGIN: 0}
            counts.update({origin: count for origin, count in db.execute(query)})
            status[table] = counts
    return status
