"""Recordings without footage are never offered, priced or searched for a new object.

needsIndexing, its cost estimate and recordingIds, and a POST /api/concepts pass cover only
ready recordings that have footage. A day with only footage-less recordings has no
needsIndexing, a concept request answers done with no recordings and spends nothing, and
search keeps its existing "no footage on this day" note (no new wording).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from api_fakes import FakeLayout, FakePerception, InMemoryLibrary, InMemoryTrackStore
from api_support import build_app
from fastapi.testclient import TestClient

from askfootage.application.concepts import ConceptBackend, ConceptService
from askfootage.application.library import Library
from askfootage.application.search import NO_FOOTAGE_ANY_CAMERA_NOTE, NO_FOOTAGE_NOTE
from askfootage.ports.library_store import Recording
from askfootage.settings import Settings

DAY = "2026-10-29"
EMPTY_DAY = "2026-11-01"
QUESTION = "someone carrying a box"


def _cost(frames: int) -> Decimal:
    return Decimal("0.0002") * frames


def _generated(recording_id: str, day: str, start: time) -> Recording:
    return replace(
        Recording(recording_id, "CAM-001", date.fromisoformat(day), start, 600, "ready"),
        has_footage=False,
    )


class World:
    """An app with a ConceptService over a library; `library` can be changed first."""

    def __init__(self, library: InMemoryLibrary, settings: Settings, videos: Path) -> None:
        self.library = library
        self.perception = FakePerception()
        self.tracks = InMemoryTrackStore(library)
        service = ConceptService(
            Library.from_store(library),
            ConceptBackend(self.perception, FakeLayout(), self.tracks, _cost),  # type: ignore[arg-type]
        )
        app = build_app(library, settings, videos, tracks=self.tracks, concepts=service)
        self.client = TestClient(app)

    def search(self, day: str, camera: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"question": QUESTION, "day": day}
        if camera:
            body["camera"] = camera
        response = self.client.post("/api/search", json=body)
        assert response.status_code == 200, response.text
        return response.json()  # type: ignore[no-any-return]


@pytest.fixture
def world_factory(fake_settings: Settings, videos_dir: Path) -> Iterator[Any]:
    made: list[World] = []

    def make(library: InMemoryLibrary) -> World:
        made.append(World(library, fake_settings, videos_dir))
        return made[-1]

    yield make
    for each in made:
        each.client.close()


def _need(answer: dict[str, Any]) -> dict[str, Any]:
    (need,) = [n for n in answer["needsIndexing"] if n["noun"] == "cardboard box"]
    return need  # type: ignore[no-any-return]


def test_footage_less_recordings_are_not_in_needs_indexing_ids_or_estimate(
    world_factory: Any,
) -> None:
    baseline = world_factory(InMemoryLibrary.from_seed())
    expected = _need(baseline.search(DAY))

    library = InMemoryLibrary.from_seed()
    for n in range(3):
        library.add_recording(_generated(f"gen-{n}", DAY, time(8, n)))
    mixed = world_factory(library)
    got = _need(mixed.search(DAY))

    assert got["recordingIds"] == expected["recordingIds"]
    assert not any(i.startswith("gen-") for i in got["recordingIds"])
    assert got["estimatedCostUsd"] == expected["estimatedCostUsd"]


def test_a_pass_covers_only_recordings_with_footage_and_spends_nothing_on_the_rest(
    world_factory: Any,
) -> None:
    library = InMemoryLibrary.from_seed()
    for n in range(3):
        library.add_recording(_generated(f"gen-{n}", DAY, time(8, n)))
    world = world_factory(library)
    response = world.client.post(
        "/api/concepts", json={"noun": "cardboard box", "confirm": True, "day": DAY}
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["recordingIds"] and not any(i.startswith("gen-") for i in body["recordingIds"])
    expected_cost = (
        Decimal("0.0002")
        * 5
        * sum(r.length_seconds for r in library.recordings.values() if r.id in body["recordingIds"])
    )
    assert body["estimatedCostUsd"] == pytest.approx(float(expected_cost))
    assert not any("gen-" in str(path) for path, _ in world.perception.calls)


def test_the_seven_day_window_pass_also_skips_them(world_factory: Any) -> None:
    library = InMemoryLibrary.from_seed()
    library.add_recording(_generated("gen-w", "2026-10-30", time(8, 0)))
    world = world_factory(library)
    body = world.client.post(
        "/api/concepts", json={"noun": "cardboard box", "confirm": True}
    ).json()
    assert "gen-w" not in body["recordingIds"]


def test_a_day_of_only_footage_less_recordings_needs_nothing_and_a_pass_is_done(
    world_factory: Any,
) -> None:
    library = InMemoryLibrary.from_seed()
    for n in range(4):
        library.add_recording(_generated(f"gen-e{n}", EMPTY_DAY, time(8, n)))
    world = world_factory(library)

    answer = world.search(EMPTY_DAY)
    assert answer["clips"] == []
    assert answer["needsIndexing"] == []

    response = world.client.post(
        "/api/concepts", json={"noun": "cardboard box", "confirm": True, "day": EMPTY_DAY}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "done"
    assert body["recordingIds"] == []
    assert body["estimatedCostUsd"] == 0
    assert world.perception.calls == []  # nothing was sent, so nothing was spent
    assert world.tracks.calls == []


def test_the_no_footage_note_keeps_its_wording_for_a_day_with_only_footage_less_rows(
    world_factory: Any,
) -> None:
    library = InMemoryLibrary.from_seed()
    library.add_recording(_generated("gen-n1", EMPTY_DAY, time(8, 0)))
    world = world_factory(library)
    assert world.search(EMPTY_DAY)["note"] == NO_FOOTAGE_ANY_CAMERA_NOTE
    assert world.search(EMPTY_DAY, "CAM-001")["note"] == NO_FOOTAGE_NOTE
    # And a day with nothing at all says the same, so the two cases read alike.
    assert world.search("2026-11-02")["note"] == NO_FOOTAGE_ANY_CAMERA_NOTE
    assert NO_FOOTAGE_NOTE == "There is no footage from this camera on this day."
    assert NO_FOOTAGE_ANY_CAMERA_NOTE == "There is no footage from any camera on this day."
