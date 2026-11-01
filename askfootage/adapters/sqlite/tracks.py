"""SQLite store for object tracks: the TrackStore port over the library's own database.

SqliteTrackStore implements askfootage/ports/track_store.py. It is built from a
SqliteLibraryStore and works in the same file through that store's connections and
transactions, so it shares everything that keeps the file safe (foreign keys on, FULL
synchronous writes, WAL, the busy timeout, BEGIN IMMEDIATE for every write, safe error
messages) and the one place that creates and upgrades the schema. A video is a recording:
tracks reference recordings, so deleting a recording, or the camera that made it, removes
its tracks and their points too.

Tables (schema.sql, version 4): tracks holds one row per (recording, label, track_id);
track_points one row per (track, frame), the box in four REAL columns; concepts_searched one
row per (recording, label) that was searched, found or not. A frame number is a
frame of the recording's constant-frame-rate working copy (askfootage/domain/timebase.py).

save_tracks checks everything it can before it touches the file, then deletes the concept's
old tracks (their points go by cascade) and writes the new ones in one transaction: a track
row each, then every point of every track in one executemany. A failure anywhere rolls the
whole call back, leaving the old tracks exactly as they were.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import groupby
from operator import itemgetter

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint
from askfootage.ports.library_store import MissingReferenceError

_PointRow = tuple[int, int, float, float, float, float]
"""One point of one track, as written and read: (track row or track_id, frame, x1, y1, x2,
y2)."""

# --- Fixed SQL. Values are always bound as parameters, never formatted in. ------------

_RECORDING_EXISTS = "SELECT 1 FROM recordings WHERE id = ?"
# Removes a concept's tracks; the schema cascades to their points.
_DELETE_CONCEPT = "DELETE FROM tracks WHERE recording_id = ? AND label = ?"
_DELETE_VIDEO = "DELETE FROM tracks WHERE recording_id = ?"
_DELETE_MARKERS = "DELETE FROM concepts_searched WHERE recording_id = ?"
# The "searched" marker; saving the same concept again keeps the one row. ON CONFLICT is
# used rather than OR IGNORE, which would also swallow a label the CHECK refuses.
_MARK_SEARCHED = """
    INSERT INTO concepts_searched (recording_id, label) VALUES (?, ?)
    ON CONFLICT (recording_id, label) DO NOTHING
"""
# A marker, or (for data saved before markers existed) at least one track.
_CONCEPT_DONE = """
    SELECT EXISTS (SELECT 1 FROM concepts_searched WHERE recording_id = ? AND label = ?)
        OR EXISTS (SELECT 1 FROM tracks WHERE recording_id = ? AND label = ?)
"""
_INSERT_TRACK = """
    INSERT INTO tracks (recording_id, label, track_id) VALUES (?, ?, ?) RETURNING id
"""
_INSERT_POINT = """
    INSERT INTO track_points (track_row, frame, x1, y1, x2, y2) VALUES (?, ?, ?, ?, ?, ?)
"""
# Every point of one recording's tracks for one label, by track_id and then frame: the
# tracks UNIQUE index gives the track order and track_points' primary key the frame order,
# so SQLite never sorts. A track row without points (impossible through this store) is
# skipped by the join rather than read as an invalid Track.
_POINTS_OF_TRACKS = """
    SELECT t.track_id, p.frame, p.x1, p.y1, p.x2, p.y2
    FROM tracks AS t
    JOIN track_points AS p ON p.track_row = t.id
    WHERE t.recording_id = ? AND t.label = ?
    ORDER BY t.track_id, p.frame
"""


class SqliteTrackStore:
    """Object tracks of each recording, in the library's SQLite file.

    Implements TrackStore from askfootage/ports/track_store.py. Safe to share between
    threads, like the library store it is built from.
    """

    def __init__(self, library: SqliteLibraryStore) -> None:
        """Keep tracks in `library`'s database, which has already been opened and checked."""
        if not isinstance(library, SqliteLibraryStore):
            raise TypeError("a SqliteTrackStore needs the SqliteLibraryStore it shares a file with")
        self._library = library

    def save_tracks(self, video_id: str, concept: str, tracks: Sequence[Track]) -> None:
        """Replace every track saved for this video and concept with `tracks`, atomically.

        Every track's label must equal `concept` and track ids must be unique, else
        ValueError (nothing is written). An empty `tracks` clears the concept's tracks but
        still records that the concept was searched (see concept_done). Raises
        MissingReferenceError if the video does not exist, TypeError if an item is not a
        Track, and LibraryError if a number is too large for SQLite (nothing is written).
        """
        tracks = tuple(tracks)  # one stable snapshot to check and then write
        _check_tracks(concept, tracks)
        with self._library._transaction(write=True) as db:
            if db.execute(_RECORDING_EXISTS, (video_id,)).fetchone() is None:
                raise MissingReferenceError("there is no recording with this id")
            db.execute(_DELETE_CONCEPT, (video_id, concept))
            db.execute(_MARK_SEARCHED, (video_id, concept))
            points: list[_PointRow] = []
            for track in tracks:
                (row,) = db.execute(_INSERT_TRACK, (video_id, concept, track.track_id)).fetchone()
                points.extend(_point_values(row, point) for point in track.points)
            db.executemany(_INSERT_POINT, points)

    def tracks_for(self, video_id: str, label: str) -> list[Track]:
        """Tracks of this video with this label, ordered by track_id, points by frame.

        An unknown video or label returns an empty list. Labels are matched exactly.
        """
        with self._library._transaction(write=False) as db:
            rows = db.execute(_POINTS_OF_TRACKS, (video_id, label)).fetchall()
        return _tracks_from_rows(label, rows)

    def concept_done(self, video_id: str, concept: str) -> bool:
        """Whether this concept was already searched for this video.

        True when save_tracks ran for it (even with no tracks: "ran, empty") or when it has
        tracks. False for a concept never searched and for an unknown video.
        """
        with self._library._transaction(write=False) as db:
            params = (video_id, concept, video_id, concept)
            return db.execute(_CONCEPT_DONE, params).fetchone()[0] == 1

    def delete_video(self, video_id: str) -> int:
        """Remove every track and searched-concept marker of this video.

        Returns how many tracks were removed. The recording itself, and its clips, stay. An
        unknown video removes nothing (0).
        """
        with self._library._transaction(write=True) as db:
            db.execute(_DELETE_MARKERS, (video_id,))
            return db.execute(_DELETE_VIDEO, (video_id,)).rowcount


def _check_tracks(concept: str, tracks: tuple[Track, ...]) -> None:
    """The port's rules for one save, checked before anything is written."""
    if not isinstance(concept, str):
        raise TypeError("concept must be a str")
    seen: set[int] = set()
    for track in tracks:
        if not isinstance(track, Track):
            raise TypeError("every item saved must be a Track")
        if track.label != concept:
            raise ValueError("every track's label must equal the concept it is saved under")
        if track.track_id in seen:
            raise ValueError("track ids must be unique within one save")
        seen.add(track.track_id)


def _point_values(track_row: int, point: TrackPoint) -> _PointRow:
    box = point.box
    return (
        track_row,
        point.frame,
        float(box.x1),
        float(box.y1),
        float(box.x2),
        float(box.y2),
    )


def _tracks_from_rows(label: str, rows: Sequence[_PointRow]) -> list[Track]:
    """Tracks for rows in _POINTS_OF_TRACKS' column order, which keeps each track's rows
    together and in frame order."""
    return [
        Track(
            track_id=track_id,
            label=label,
            points=tuple(
                TrackPoint(frame=frame, box=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2))
                for _, frame, x1, y1, x2, y2 in group
            ),
        )
        for track_id, group in groupby(rows, key=itemgetter(0))
    ]
