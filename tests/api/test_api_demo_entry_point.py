"""The entry point uvicorn uses: create_app() with no arguments serves the demo library.

`python -m uvicorn askfootage.interfaces.api.app:create_app --factory` calls create_app()
with no arguments. Here load_settings() is replaced by fake settings whose data directory
is a temp folder, so the real .env is never read and nothing is written outside tmp_path.
This is the one API test that runs on the real SQLite store, seeded from
contract/examples/demo-seed.json.
"""

from __future__ import annotations

from datetime import date

import pytest
from api_fakes import load_example
from fastapi.testclient import TestClient

from askfootage.interfaces.api import app as app_module
from askfootage.settings import Settings


@pytest.fixture
def demo_settings(fake_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Make create_app() load the fake settings instead of reading the environment."""
    monkeypatch.setattr(app_module, "load_settings", lambda: fake_settings)
    return fake_settings


def test_the_factory_with_no_arguments_serves_the_seeded_demo(demo_settings: Settings) -> None:
    with TestClient(app_module.create_app()) as client:
        assert client.get("/api/status").json() == load_example("status.json")
        days = client.get("/api/days", params={"camera": "loading-dock"}).json()
        recordings = client.get(
            "/api/recordings", params={"day": "2026-10-29", "camera": "loading-dock"}
        ).json()
        answer = client.post(
            "/api/search",
            json={
                "question": "someone carrying a box",
                "day": "2026-10-29",
                "camera": "loading-dock",
            },
        ).json()
        clip = client.get("/api/clips/clip-1029-104215").json()
        zones = client.get("/api/zones").json()
        saved = client.get("/api/saved-clips").json()
    assert days == load_example("days.json")
    assert recordings == load_example("recordings.json")
    assert answer == load_example("search-response.json")
    assert clip == load_example("clip-detail.json")
    assert zones == load_example("zones.json")
    assert saved == []


def test_the_demo_database_lives_in_the_data_dir(demo_settings: Settings) -> None:
    app_module.create_app()
    assert (demo_settings.data_dir / app_module.DEMO_DATABASE_NAME).is_file()


def test_a_restart_keeps_changes_and_does_not_seed_again(demo_settings: Settings) -> None:
    with TestClient(app_module.create_app()) as client:
        assert client.delete("/api/zones/zone-exit-lane").status_code == 204
        created = client.post("/api/saved-clips", json={"clipId": "clip-1029-104215"})
        assert created.status_code == 201
    with TestClient(app_module.create_app()) as client:
        assert [zone["id"] for zone in client.get("/api/zones").json()] == ["zone-loading-door"]
        assert [s["clip"]["id"] for s in client.get("/api/saved-clips").json()] == [
            "clip-1029-104215"
        ]


def test_settings_passed_in_are_used_without_loading_any(
    fake_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_load() -> Settings:
        raise AssertionError("load_settings() must not be called when settings are given")

    monkeypatch.setattr(app_module, "load_settings", must_not_load)
    with TestClient(app_module.create_app(fake_settings)) as client:
        assert client.get("/api/status").json()["demoMode"] is True


def test_demo_today_is_the_seed_files_today() -> None:
    assert app_module.read_demo_today() == date(2026, 10, 30)


def test_the_module_builds_no_app_on_import() -> None:
    # A module-level app would open (and maybe create) a database just by being imported.
    assert not hasattr(app_module, "app")
