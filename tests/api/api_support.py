"""Constants and helpers shared by the API tests (fixtures live in conftest.py)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from api_fakes import InMemoryLibrary
from fastapi import FastAPI

from askfootage.application.library import Library
from askfootage.interfaces.api.app import create_app
from askfootage.settings import Settings

# Fake and low-entropy on purpose, so no secret scanner mistakes it for a real key.
FAKE_KEY = "sk-test-" + "not-a-real-key-" * 4
TODAY = date(2026, 10, 30)
NOW = datetime(2026, 10, 30, 9, 12, 44, 987654, tzinfo=UTC)
ENV_NAMES = ("META_API_KEY", "META_API_BASE_URL", "MAX_RUN_COST_USD", "DATA_DIR", "ASKFOOTAGE_DEMO")
UI_ORIGIN = "http://localhost:5173"


def build_app(
    store: InMemoryLibrary, settings: Settings, videos_dir: Path, **overrides: Any
) -> FastAPI:
    """The API on the given store, with today 2026-10-30 and a fixed UTC clock."""
    options: dict[str, Any] = {
        "library": Library.from_store(store),
        "today": lambda: TODAY,
        "utc_now": lambda: NOW,
        "videos_dir": videos_dir,
    }
    options.update(overrides)
    return create_app(settings, **options)


def assert_error(response: httpx.Response, status: int, code: str) -> str:
    """Check the status and that the body is exactly the standard error; return the message."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    message = body["error"]["message"]
    assert isinstance(message, str) and message
    return message
