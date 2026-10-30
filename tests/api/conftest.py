"""Fixtures for the API tests: an app on in-memory stores seeded with the demo dataset.

Nothing here reads the real .env, touches data/ or opens a network connection. Settings
are built with env_file disabled and an obviously fake key, so tests can prove the key
never reaches a response.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from api_fakes import FAKE_MP4, InMemoryLibrary
from api_support import ENV_NAMES, FAKE_KEY, build_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from askfootage.settings import Settings


@pytest.fixture
def fake_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings with a fake key, built from no .env file and a cleaned environment."""
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None, META_API_KEY=FAKE_KEY, DATA_DIR=str(tmp_path / "data"))


@pytest.fixture
def store() -> InMemoryLibrary:
    """A fresh in-memory library holding the demo dataset."""
    return InMemoryLibrary.from_seed()


@pytest.fixture
def videos_dir(tmp_path: Path) -> Path:
    """A videos folder holding a tiny fake clip1.mp4."""
    directory = tmp_path / "videos"
    directory.mkdir()
    (directory / "clip1.mp4").write_bytes(FAKE_MP4)
    return directory


@pytest.fixture
def app(store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path) -> FastAPI:
    """The API on the seeded in-memory store."""
    return build_app(store, fake_settings, videos_dir)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """A TestClient for the app. Server errors come back as 500 responses, never raised."""
    with TestClient(app) as test_client:
        yield test_client
