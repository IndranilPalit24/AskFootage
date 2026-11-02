"""Object tracks through the TrackStore port: round trips, replace semantics, refusals that
write nothing, deleting a video's tracks, and hostile text stored as plain text."""

from pathlib import Path

import pytest
from db_library_helpers import CAM_1, count_rows, raw_connection, recording, track

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.adapters.sqlite.tracks import SqliteTrackStore
from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint
from askfootage.ports.library_store import LibraryError, MissingReferenceError
from askfootage.ports.track_store import TrackStore

INJECTION = "x'); DROP TABLE tracks;--"


@pytest.fixture
def tracks(stocked_store: SqliteLibraryStore) -> SqliteTrackStore:
    """A track store over a library holding CAM-001 with recordings rec-1 and rec-2."""
    stocked_store.add_recording(recording("rec-2", CAM_1))
    return SqliteTrackStore(stocked_store)


def _point_rows(path: Path) -> int:
    return count_rows(path, "track_points")


def test_the_track_store_stands_in_for_the_port(tracks: SqliteTrackStore) -> None:
    port: TrackStore = tracks
    assert port.tracks_for("rec-1", "person") == []


def test_tracks_round_trip_exactly_with_gaps_and_awkward_floats(
    tracks: SqliteTrackStore,
) -> None:
    awkward = (
        BoundingBox(0.1 + 0.2, 1 / 3, 0.30000000000000004 + 1e-9, 2 / 3),
        BoundingBox(-5.5, 1e-7, 1e-300, 7.0),
        BoundingBox(1e15 + 0.5, 2.718281828459045, 1e15 + 0.75, 3.141592653589793),
        BoundingBox(0.0, 0.0, 0.0, 0.0),
    )
    gappy = Track(
        track_id=3,
        label="person",
        points=tuple(
            TrackPoint(frame, box) for frame, box in zip((0, 4, 5, 2**40), awkward, strict=True)
        ),
    )
    saved = [gappy, track(1, frames=(7,)), track(2, frames=(1, 3, 9, 27))]

    tracks.save_tracks("rec-1", "person", saved)
    found = tracks.tracks_for("rec-1", "person")

    assert found == sorted(saved, key=lambda t: t.track_id)
    assert [t.track_id for t in found] == [1, 2, 3]
    back = found[2]
    assert back.frames == (0, 4, 5, 2**40)
    for got, want in zip(back.points, gappy.points, strict=True):
        for name in ("x1", "y1", "x2", "y2"):
            value = getattr(got.box, name)
            assert type(value) is float
            assert value.hex() == float(getattr(want.box, name)).hex()  # bit for bit


def test_integer_coordinates_come_back_as_equal_floats(tracks: SqliteTrackStore) -> None:
    whole = track(1, box=BoundingBox(1, 2, 3, 4))
    tracks.save_tracks("rec-1", "person", [whole])
    [found] = tracks.tracks_for("rec-1", "person")
    assert found == whole
    assert found.points[0].box.x1 == 1.0 and type(found.points[0].box.x1) is float


def test_a_tuple_and_a_list_are_both_accepted(tracks: SqliteTrackStore) -> None:
    tracks.save_tracks("rec-1", "person", (track(1),))
    tracks.save_tracks("rec-2", "person", [track(1)])
    assert tracks.tracks_for("rec-1", "person") == tracks.tracks_for("rec-2", "person")


def test_unknown_video_or_label_reads_as_empty(tracks: SqliteTrackStore) -> None:
    tracks.save_tracks("rec-1", "person", [track(1)])
    assert tracks.tracks_for("rec-nope", "person") == []
    assert tracks.tracks_for("rec-2", "person") == []
    assert tracks.tracks_for("rec-1", "cardboard box") == []
    assert tracks.tracks_for("rec-1", "Person") == []  # labels are matched exactly


def test_concepts_and_videos_are_kept_apart(tracks: SqliteTrackStore) -> None:
    people = [track(1), track(2, frames=(5, 6))]
    boxes = [track(1, "cardboard box", frames=(2,))]
    other = [track(9, frames=(100,))]
    tracks.save_tracks("rec-1", "person", people)
    tracks.save_tracks("rec-1", "cardboard box", boxes)
    tracks.save_tracks("rec-2", "person", other)

    assert tracks.tracks_for("rec-1", "person") == people
    assert tracks.tracks_for("rec-1", "cardboard box") == boxes
    assert tracks.tracks_for("rec-2", "person") == other


def test_saving_again_replaces_the_concepts_tracks_and_their_points(
    tracks: SqliteTrackStore, library_path: Path
) -> None:
    tracks.save_tracks("rec-1", "person", [track(1), track(2), track(3)])
    tracks.save_tracks("rec-1", "cardboard box", [track(1, "cardboard box")])
    assert _point_rows(library_path) == 12

    replacement = [track(2, frames=(40, 41)), track(4, frames=(50,))]
    tracks.save_tracks("rec-1", "person", replacement)

    assert tracks.tracks_for("rec-1", "person") == replacement
    assert tracks.tracks_for("rec-1", "cardboard box") == [track(1, "cardboard box")]
    assert count_rows(library_path, "tracks") == 3
    assert _point_rows(library_path) == 3 + 3  # no stale points from the replaced tracks


def test_saving_no_tracks_clears_only_that_concept(
    tracks: SqliteTrackStore, library_path: Path
) -> None:
    tracks.save_tracks("rec-1", "person", [track(1), track(2)])
    tracks.save_tracks("rec-1", "cardboard box", [track(1, "cardboard box")])
    tracks.save_tracks("rec-2", "person", [track(1)])

    tracks.save_tracks("rec-1", "person", [])

    assert tracks.tracks_for("rec-1", "person") == []
    assert tracks.tracks_for("rec-1", "cardboard box") == [track(1, "cardboard box")]
    assert tracks.tracks_for("rec-2", "person") == [track(1)]
    assert _point_rows(library_path) == 6


def _snapshot(path: Path) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    with raw_connection(path) as db:
        return (
            db.execute("SELECT * FROM tracks ORDER BY id").fetchall(),
            db.execute("SELECT * FROM track_points ORDER BY track_row, frame").fetchall(),
        )


@pytest.mark.parametrize(
    "bad",
    [
        [track(1), track(2, "cardboard box")],
        [track(1, "persons")],
        [track(1, "box")],
    ],
    ids=["one-of-two", "near-miss", "other-noun"],
)
def test_a_label_that_is_not_the_concept_is_refused_and_nothing_is_written(
    tracks: SqliteTrackStore, library_path: Path, bad: list[Track]
) -> None:
    tracks.save_tracks("rec-1", "person", [track(7)])
    before = _snapshot(library_path)

    with pytest.raises(ValueError, match="label"):
        tracks.save_tracks("rec-1", "person", bad)

    assert _snapshot(library_path) == before
    assert tracks.tracks_for("rec-1", "person") == [track(7)]


def test_repeated_track_ids_are_refused_and_nothing_is_written(
    tracks: SqliteTrackStore, library_path: Path
) -> None:
    tracks.save_tracks("rec-1", "person", [track(7)])
    before = _snapshot(library_path)

    with pytest.raises(ValueError, match="track id"):
        tracks.save_tracks("rec-1", "person", [track(1), track(2), track(1, frames=(9,))])

    assert _snapshot(library_path) == before


def test_something_that_is_not_a_track_is_refused(
    tracks: SqliteTrackStore, library_path: Path
) -> None:
    with pytest.raises(TypeError):
        tracks.save_tracks("rec-1", "person", [track(1), ("person", 2)])  # type: ignore[list-item]
    assert _snapshot(library_path) == ([], [])


@pytest.mark.parametrize("saved", [[], [track(1)]], ids=["clearing", "saving"])
def test_an_unknown_video_is_a_missing_reference_and_nothing_is_written(
    tracks: SqliteTrackStore, library_path: Path, saved: list[Track]
) -> None:
    with pytest.raises(MissingReferenceError):
        tracks.save_tracks("rec-nope", "person", saved)
    assert _snapshot(library_path) == ([], [])


def test_a_write_that_fails_halfway_leaves_the_old_tracks(
    tracks: SqliteTrackStore, library_path: Path
) -> None:
    """The second track's id does not fit SQLite's 64-bit integer, so the INSERT fails after
    the delete and the first insert ran; the transaction must undo both."""
    tracks.save_tracks("rec-1", "person", [track(7)])
    before = _snapshot(library_path)

    with pytest.raises(LibraryError):
        tracks.save_tracks("rec-1", "person", [track(1), track(2**63)])

    assert _snapshot(library_path) == before
    assert tracks.tracks_for("rec-1", "person") == [track(7)]


def test_delete_video_removes_only_that_videos_tracks(
    tracks: SqliteTrackStore, stocked_store: SqliteLibraryStore, library_path: Path
) -> None:
    tracks.save_tracks("rec-1", "person", [track(1), track(2)])
    tracks.save_tracks("rec-1", "cardboard box", [track(1, "cardboard box")])
    tracks.save_tracks("rec-2", "person", [track(5)])

    assert tracks.delete_video("rec-1") == 3

    assert tracks.tracks_for("rec-1", "person") == []
    assert tracks.tracks_for("rec-1", "cardboard box") == []
    assert tracks.tracks_for("rec-2", "person") == [track(5)]
    assert _point_rows(library_path) == 3
    assert stocked_store.get_recording("rec-1") == recording()  # the recording stays
    assert stocked_store.get_clip("clip-1") is not None
    assert tracks.delete_video("rec-1") == 0
    assert tracks.delete_video("rec-nope") == 0


def test_tracks_survive_reopening_the_file(tracks: SqliteTrackStore, library_path: Path) -> None:
    tracks.save_tracks("rec-1", "person", [track(1), track(2, frames=(3, 8))])
    reopened = SqliteTrackStore(SqliteLibraryStore(library_path))
    assert reopened.tracks_for("rec-1", "person") == [track(1), track(2, frames=(3, 8))]


def test_an_injection_string_label_is_stored_as_plain_text(
    tracks: SqliteTrackStore, library_path: Path
) -> None:
    hostile = track(1, INJECTION)
    tracks.save_tracks("rec-1", INJECTION, [hostile])
    tracks.save_tracks("rec-1", "person", [track(2)])

    assert tracks.tracks_for("rec-1", INJECTION) == [hostile]
    assert tracks.tracks_for(INJECTION, INJECTION) == []
    assert tracks.delete_video(INJECTION) == 0
    with raw_connection(library_path) as db:
        labels = sorted(row[0] for row in db.execute("SELECT label FROM tracks"))
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    assert labels == sorted([INJECTION, "person"])
    assert {"tracks", "track_points"} <= names
    assert tracks.tracks_for("rec-1", "person") == [track(2)]


def test_labels_for_lists_distinct_labels_sorted(tracks: SqliteTrackStore) -> None:
    assert tracks.labels_for("rec-1") == []
    tracks.save_tracks("rec-1", "person", [track(0, "person"), track(1, "person")])
    tracks.save_tracks("rec-1", "hand", [track(0, "hand")])
    assert tracks.labels_for("rec-1") == ["hand", "person"]
    assert tracks.labels_for("rec-2") == []
    assert tracks.labels_for("nope") == []
