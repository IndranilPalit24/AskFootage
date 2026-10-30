"""One store shared by many threads, as FastAPI's thread pool will share it."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from db_library_helpers import camera, clip, raw_connection, recording, zone

from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.ports.library_store import DuplicateError

THREADS = 8
ROUNDS = 5
DAY = date(2026, 10, 29)


def _prepare(store: SqliteLibraryStore, clips: int) -> None:
    store.add_camera(camera())
    store.add_recording(recording())
    for index in range(clips):
        store.add_clip(
            clip(
                f"clip-{index}",
                start_time=time(10, index // 60, index % 60),
                start_seconds=index,
                end_seconds=index + 1,
            )
        )


def test_threads_reading_and_writing_at_once_all_succeed(
    store: SqliteLibraryStore, library_path: Path
) -> None:
    _prepare(store, THREADS * ROUNDS)
    start = threading.Barrier(THREADS)
    base_time = datetime(2026, 10, 30, 9, tzinfo=UTC)

    def work(worker: int) -> int:
        start.wait()
        done = 0
        for round_ in range(ROUNDS):
            item = worker * ROUNDS + round_
            store.add_zone(zone(f"zone-{item}", name=f"Zone {item}"))
            store.replace_zone(zone(f"zone-{item}", name=f"Renamed {item}"))
            store.add_saved_clip(
                f"saved-{item}", f"clip-{item}", f"note {item}", base_time + timedelta(seconds=item)
            )
            assert store.update_note(f"saved-{item}", "changed") is not None
            assert len(store.list_clips("cam-1", DAY)) == THREADS * ROUNDS
            assert store.get_clip(f"clip-{item}") is not None
            store.list_zones("cam-1")
            store.list_saved_clips(DAY)
            store.summarise_days("cam-1", DAY, DAY)
            done += 1
        return done

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        results = list(pool.map(work, range(THREADS)))

    assert results == [ROUNDS] * THREADS
    assert len(store.list_zones()) == THREADS * ROUNDS
    saved = store.list_saved_clips()
    assert len(saved) == THREADS * ROUNDS
    assert {s.note for s in saved} == {"changed"}
    with raw_connection(library_path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_racing_to_save_the_same_clip_lets_exactly_one_thread_win(
    store: SqliteLibraryStore,
) -> None:
    _prepare(store, 1)
    start = threading.Barrier(THREADS)

    def save(worker: int) -> str:
        start.wait()
        try:
            store.add_saved_clip(f"saved-{worker}", "clip-0", "", datetime.now(UTC))
        except DuplicateError:
            return "duplicate"
        return "saved"

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        outcomes = list(pool.map(save, range(THREADS)))

    assert sorted(outcomes) == ["duplicate"] * (THREADS - 1) + ["saved"]
    assert len(store.list_saved_clips()) == 1


def test_racing_to_name_zones_alike_lets_exactly_one_thread_win(
    store: SqliteLibraryStore,
) -> None:
    _prepare(store, 0)
    start = threading.Barrier(THREADS)

    def add(worker: int) -> bool:
        start.wait()
        try:
            store.add_zone(zone(f"zone-{worker}", name="Same name"))
        except DuplicateError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        wins = sum(pool.map(add, range(THREADS)))

    assert wins == 1
    assert [z.name for z in store.list_zones()] == ["Same name"]


# Eight spellings that differ only in case. The UNIQUE index cannot see them as one name,
# so only the store's casefold check, inside its write lock, can keep this to one winner.
_CASE_VARIANTS = [
    "Same name",
    "same name",
    "SAME NAME",
    "Same Name",
    "sAME nAME",
    "same NAME",
    "SAME name",
    "SaMe NaMe",
]


def test_racing_to_name_zones_alike_in_different_cases_lets_exactly_one_thread_win(
    store: SqliteLibraryStore,
) -> None:
    assert len(set(_CASE_VARIANTS)) == THREADS
    _prepare(store, 0)
    start = threading.Barrier(THREADS)

    def add(worker: int) -> bool:
        start.wait()
        try:
            store.add_zone(zone(f"zone-{worker}", name=_CASE_VARIANTS[worker]))
        except DuplicateError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        wins = sum(pool.map(add, range(THREADS)))

    assert wins == 1
    [kept] = store.list_zones()
    assert kept.name in _CASE_VARIANTS


def test_separate_store_objects_on_one_file_see_each_others_writes(library_path: Path) -> None:
    writer = SqliteLibraryStore(library_path)
    reader = SqliteLibraryStore(library_path)
    _prepare(writer, 1)
    writer.add_zone(zone())
    assert reader.get_zone("zone-1") == zone()
