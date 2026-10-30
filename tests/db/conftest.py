"""Fixtures for the library store tests: every database is a fresh file in tmp_path."""

from pathlib import Path

import pytest
from db_library_helpers import DEMO_SEED, camera, clip, recording

from askfootage.adapters.sqlite.store import SqliteLibraryStore, seed_demo_data


@pytest.fixture
def library_path(tmp_path: Path) -> Path:
    """Where the test's library database lives (created by the store fixture)."""
    return tmp_path / "library" / "index.sqlite"


@pytest.fixture
def store(library_path: Path) -> SqliteLibraryStore:
    """An empty library."""
    return SqliteLibraryStore(library_path)


@pytest.fixture
def stocked_store(store: SqliteLibraryStore) -> SqliteLibraryStore:
    """A library holding camera cam-1, recording rec-1 (29 Oct 2026, 10:00) and clip-1."""
    store.add_camera(camera())
    store.add_recording(recording())
    store.add_clip(clip())
    return store


@pytest.fixture
def seeded_store(store: SqliteLibraryStore) -> SqliteLibraryStore:
    """A library loaded from contract/examples/demo-seed.json."""
    assert seed_demo_data(store, DEMO_SEED) is True
    return store
