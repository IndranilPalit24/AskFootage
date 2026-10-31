"""POST /api/search over HTTP: the demo keyword search on the seeded Thursday 29 October.

Most tests ask about CAM-001 (the loading dock, the contract example's camera). The tests
at the end leave the camera out, which searches every camera.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, time
from typing import Any

import pytest
from api_fakes import InMemoryLibrary, load_example
from api_support import assert_error
from fastapi.testclient import TestClient

from askfootage.ports.library_store import Recording

THURSDAY = "2026-10-29"
CARRYING_ON_THURSDAY = [
    "clip-1029-061405",
    "clip-1029-070903",
    "clip-1029-091522",
    "clip-1029-104215",
    "clip-1029-130610",
]
ALL_READY_ON_THURSDAY = [
    "clip-1029-061405",
    "clip-1029-070903",
    "clip-1029-072140",
    "clip-1029-091522",
    "clip-1029-104215",
    "clip-1029-104847",
    "clip-1029-130610",
    "clip-1029-131430",
]
NOT_READY_NOTE = "1 recording on this day is still being indexed, so it was not searched."
CAM2_CARRYING = "clip-1029-cam2-071230"


def ask(client: TestClient, question: Any, day: str = THURSDAY, **extra: Any) -> Any:
    """POST a question about the loading dock (CAM-001) and return the response."""
    body = {"question": question, "day": day, "camera": "CAM-001", **extra}
    return client.post("/api/search", json=body)


def ask_all(client: TestClient, question: str, day: str = THURSDAY) -> Any:
    """POST a question about every camera (no camera field) and return the response."""
    return client.post("/api/search", json={"question": question, "day": day})


def clip_ids(response: Any) -> list[str]:
    """The ids of the clips in a 200 search response, in order."""
    assert response.status_code == 200, response.text
    return [clip["id"] for clip in response.json()["clips"]]


def test_someone_carrying_a_box_on_thursday_is_the_contract_example(client: TestClient) -> None:
    response = ask(client, "someone carrying a box")
    assert response.json() == load_example("search-response.json")
    assert clip_ids(response) == CARRYING_ON_THURSDAY


def test_the_question_comes_back_trimmed(client: TestClient) -> None:
    response = ask(client, "   someone carrying a box \n")
    assert response.json()["question"] == "someone carrying a box"
    assert clip_ids(response) == CARRYING_ON_THURSDAY


@pytest.mark.parametrize(
    "question", ["Any PARCELS today?", "who carried packages", "boxes", "Carry"]
)
def test_carrying_words_find_the_carrying_clips(client: TestClient, question: str) -> None:
    assert clip_ids(ask(client, question)) == CARRYING_ON_THURSDAY


def test_waiting_words_find_the_dwell_clips(client: TestClient) -> None:
    ids = clip_ids(ask(client, "anyone waiting around?"))
    assert ids == ["clip-1029-072140", "clip-1029-104847", "clip-1029-131430"]


def test_a_zone_name_filters_by_zone(client: TestClient) -> None:
    ids = clip_ids(ask(client, "what happened at the exit lane"))
    assert ids == ["clip-1029-072140", "clip-1029-131430"]


def test_a_zone_name_matches_ignoring_case(client: TestClient) -> None:
    ids = clip_ids(ask(client, "LOADING DOOR"))
    assert ids == [
        "clip-1029-061405",
        "clip-1029-070903",
        "clip-1029-104215",
        "clip-1029-104847",
        "clip-1029-130610",
    ]


def test_several_concepts_must_all_hold(client: TestClient) -> None:
    carrying_at_the_door = clip_ids(ask(client, "someone carrying a box through the loading door"))
    assert carrying_at_the_door == [
        "clip-1029-061405",
        "clip-1029-070903",
        "clip-1029-104215",
        "clip-1029-130610",
    ]
    assert clip_ids(ask(client, "someone standing at the loading door")) == ["clip-1029-104847"]
    assert clip_ids(ask(client, "carrying a box in the exit lane")) == []
    assert clip_ids(ask(client, "waiting in the loading door and the exit lane")) == []


def test_only_general_words_return_every_ready_clip_of_the_day(client: TestClient) -> None:
    response = ask(client, "any people?")
    assert clip_ids(response) == ALL_READY_ON_THURSDAY
    assert response.json()["note"] == NOT_READY_NOTE


def test_clips_of_a_recording_still_indexing_are_left_out_and_noted(
    client: TestClient, store: InMemoryLibrary
) -> None:
    # Thursday's 16:10 recording is still indexing; give it a carrying clip to prove it is
    # not searched.
    seeded = store.clips["clip-1029-061405"]
    store.add_clip(replace(seeded, id="clip-hidden", recording_id="rec-1029-1610"))
    response = ask(client, "carrying")
    assert "clip-hidden" not in clip_ids(response)
    assert response.json()["note"] == NOT_READY_NOTE


def test_two_recordings_not_ready_are_counted_in_the_note(client: TestClient) -> None:
    response = ask(client, "carrying", day="2026-10-30")
    assert clip_ids(response) == ["clip-1030-065240"]
    assert response.json()["note"] == (
        "2 recordings on this day are still being indexed, so they were not searched."
    )


def test_a_day_whose_recordings_are_all_ready_has_no_note(client: TestClient) -> None:
    response = ask(client, "carrying", day="2026-10-28")
    assert clip_ids(response) == ["clip-1028-064712"]
    assert response.json()["note"] is None


def test_nothing_recognised_returns_no_clips_and_says_what_the_demo_understands(
    client: TestClient,
) -> None:
    response = ask(client, "red bicycle")
    assert clip_ids(response) == []
    note = response.json()["note"]
    assert note.startswith("The demo search did not recognise anything in this question.")
    for topic in ("carrying a box", "waiting", "Exit lane", "Loading door", "people"):
        assert topic in note
    assert note.endswith(NOT_READY_NOTE)
    assert "bicycle" not in note


def test_a_day_without_footage_says_so(client: TestClient) -> None:
    response = ask(client, "someone carrying a box", day="2026-10-25")
    assert response.json() == {
        "question": "someone carrying a box",
        "day": "2026-10-25",
        "clips": [],
        "note": "There is no footage from this camera on this day.",
        "proofs": [],
    }


def test_a_day_with_only_unready_recordings_searches_nothing(
    client: TestClient, store: InMemoryLibrary
) -> None:
    store.add_recording(
        Recording(
            id="rec-1025-0600",
            camera="CAM-001",
            day=date(2026, 10, 25),
            start_time=time(6, 0),
            length_seconds=60,
            status="waiting",
        )
    )
    response = ask(client, "people", day="2026-10-25")
    assert clip_ids(response) == []
    assert response.json()["note"] == NOT_READY_NOTE


@pytest.mark.parametrize("camera", ["garage", "CAM-999", "loading-dock"])
def test_search_on_an_unknown_camera_is_404(client: TestClient, camera: str) -> None:
    response = client.post(
        "/api/search", json={"question": "people", "day": THURSDAY, "camera": camera}
    )
    assert assert_error(response, 404, "not_found") == "Camera not found."


# --- Every camera: camera left out or null --------------------------------------------------


def test_without_a_camera_every_cameras_clips_are_searched(client: TestClient) -> None:
    response = ask_all(client, "someone carrying a box")
    ids = clip_ids(response)
    assert ids == [*CARRYING_ON_THURSDAY[:2], CAM2_CARRYING, *CARRYING_ON_THURSDAY[2:]]
    cameras = {clip["id"]: clip["camera"] for clip in response.json()["clips"]}
    assert cameras.pop(CAM2_CARRYING) == "CAM-002"
    assert set(cameras.values()) == {"CAM-001"}
    assert response.json()["note"] == NOT_READY_NOTE


def test_a_null_camera_is_the_same_as_leaving_it_out(client: TestClient) -> None:
    body = {"question": "someone carrying a box", "day": THURSDAY, "camera": None}
    with_null = client.post("/api/search", json=body)
    assert with_null.status_code == 200
    assert with_null.json() == ask_all(client, "someone carrying a box").json()


def test_one_camera_leaves_the_other_cameras_out(client: TestClient) -> None:
    assert CAM2_CARRYING not in clip_ids(ask(client, "carrying"))
    only_gate = client.post(
        "/api/search", json={"question": "carrying", "day": THURSDAY, "camera": "CAM-002"}
    )
    assert clip_ids(only_gate) == [CAM2_CARRYING]
    assert only_gate.json()["note"] is None


def test_the_note_counts_unready_recordings_across_every_camera(client: TestClient) -> None:
    # Friday: CAM-001 has one preparing and one waiting recording, CAM-002 one indexing.
    response = ask_all(client, "carrying", day="2026-10-30")
    assert clip_ids(response) == ["clip-1030-065240"]
    assert response.json()["note"] == (
        "3 recordings on this day are still being indexed, so they were not searched."
    )


def test_zone_names_of_every_camera_are_understood(client: TestClient) -> None:
    assert clip_ids(ask_all(client, "anything in the gate lane?")) == [CAM2_CARRYING]
    # CAM-001 has no zone called Gate lane, so on its own the question is not understood.
    one_camera = ask(client, "anything in the gate lane?")
    assert clip_ids(one_camera) == []
    note = one_camera.json()["note"]
    assert "Gate lane" not in note and "Loading door" in note


def test_the_not_understood_note_lists_every_cameras_zones(client: TestClient) -> None:
    note = ask_all(client, "red bicycle").json()["note"]
    assert "a zone (Exit lane, Gate lane, Loading door)" in note


def test_a_day_without_footage_on_any_camera_says_so(client: TestClient) -> None:
    response = ask_all(client, "someone carrying a box", day="2026-10-25")
    assert response.json() == {
        "question": "someone carrying a box",
        "day": "2026-10-25",
        "clips": [],
        "note": "There is no footage from any camera on this day.",
        "proofs": [],
    }


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"question": "", "day": THURSDAY, "camera": "CAM-001"}, "question: must be at least"),
        ({"question": "   \t\n ", "day": THURSDAY, "camera": "CAM-001"}, "question: must not"),
        (
            {"question": "a" * 301, "day": THURSDAY, "camera": "CAM-001"},
            "question: must be at most 300 characters",
        ),
        ({"question": 42, "day": THURSDAY, "camera": "CAM-001"}, "question: must be text"),
        ({"day": THURSDAY, "camera": "CAM-001"}, "question: is required"),
        ({"question": "people", "camera": "CAM-001"}, "day: is required"),
        ({"question": "people", "day": "yesterday", "camera": "CAM-001"}, "day: must be"),
        ({"question": "people", "day": THURSDAY, "camera": "a b"}, "camera: must be 1 to 64"),
        ({"question": "people", "day": THURSDAY, "camera": ""}, "camera: must be 1 to 64"),
        ({"question": "people", "day": THURSDAY, "camera": 7}, "camera: must be text"),
        (
            {"question": "people", "day": THURSDAY, "camera": "CAM-001", "limit": 5},
            "limit: is not an accepted field",
        ),
    ],
)
def test_bad_search_requests_are_422_naming_the_field(
    client: TestClient, body: dict[str, Any], message: str
) -> None:
    got = assert_error(client.post("/api/search", json=body), 422, "validation_error")
    assert got.startswith(message)


def test_a_300_character_question_is_accepted(client: TestClient) -> None:
    response = ask(client, "carrying " + "x" * 291)
    assert len(response.json()["question"]) == 300
    assert clip_ids(response) == CARRYING_ON_THURSDAY


def test_the_rejected_question_is_never_echoed(client: TestClient) -> None:
    question = "<script>alert(1)</script>" * 13
    message = assert_error(ask(client, question), 422, "validation_error")
    assert "script" not in message


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"{not json", "application/json"),
        (b"[]", "application/json"),
        (b"question=people", "application/x-www-form-urlencoded"),
        (b"", "application/json"),
    ],
)
def test_a_body_that_is_not_a_json_object_is_422(
    client: TestClient, content: bytes, content_type: str
) -> None:
    response = client.post("/api/search", content=content, headers={"content-type": content_type})
    assert_error(response, 422, "validation_error")
