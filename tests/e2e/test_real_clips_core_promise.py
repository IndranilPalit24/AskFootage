"""The core promise on the two real clips: "person carrying a box" finds clip2, not clip1.

Runs the real app (askfootage.interfaces.real_clips) in-process over the library that
scripts.ingest_real_clips stored. Nothing is sent anywhere. The expected times are the
confirmed ones in labels/clip2.json (the box is in the person's hands from 1 s to 5 s).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from askfootage.application.clip_labels import load_clip_labels
from askfootage.interfaces.real_clips import create_app

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "real"
DAY = "2026-10-30"

pytestmark = pytest.mark.skipif(
    not (DATA / "library.sqlite").is_file() or not (DATA / "clip2" / "prepared.mp4").is_file(),
    reason="data/real/library.sqlite and data/real/clip2/prepared.mp4 are made by "
    "scripts.ingest_real_clips; run it first",
)

PHRASINGS = [
    "person carrying a box",
    "someone carrying a cardboard box",
    "a person holding a box",
]


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(DATA))


def _search(client: TestClient, question: str) -> dict:
    response = client.post("/api/search", json={"question": question, "day": DAY})
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("question", PHRASINGS)
def test_carrying_a_box_finds_clip2_and_not_clip1(client: TestClient, question: str) -> None:
    body = _search(client, question)
    recordings = [clip["recordingId"] for clip in body["clips"]]
    assert recordings == ["clip2"]


def test_the_proof_matches_what_the_filmer_confirmed(client: TestClient) -> None:
    body = _search(client, "person carrying a box")
    (proof,) = body["proofs"]
    carried = next(
        event
        for event in load_clip_labels(ROOT / "labels" / "clip2.json").events
        if event.type == "carrying" and event.status == "confirmed"
    )
    assert proof["relation"] == "carrying"
    assert proof["trackLabels"] == ["person", "cardboard box"]
    # Within half a second of the labelled 1-5 s at both ends.
    assert abs(proof["startSeconds"] - carried.start_s) <= 0.5
    assert abs(proof["endSeconds"] - carried.end_s) <= 0.5


def test_the_snapshot_is_a_picture(client: TestClient) -> None:
    clip = _search(client, "person carrying a box")["clips"][0]
    image = client.get(clip["snapshotUrl"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert image.content[:2] == b"\xff\xd8"


@pytest.mark.parametrize("question", ["person carrying a ladder", "person riding a bicycle"])
def test_other_objects_find_nothing(client: TestClient, question: str) -> None:
    assert _search(client, question)["clips"] == []
