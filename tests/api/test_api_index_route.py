"""POST /api/recordings/{id}/index: start indexing, reply 202, do the work after the reply.

The work runs through an injected scheduler. Most tests hold the job back so they can see
the state at reply time, then run it themselves; one uses the default scheduler (FastAPI
BackgroundTasks) end to end. All fakes: no disk, no network, no Meta call.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from api_fakes import (
    FAKE_SERVER_ROOT,
    ExplodingLibrary,
    FakeLayout,
    FakePerception,
    FakePreparer,
    InMemoryLibrary,
    InMemoryTrackStore,
    load_example,
    make_track,
)
from api_support import FAKE_KEY, UI_ORIGIN, assert_error, build_app
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from askfootage.application.ingest_video import IndexingPipeline
from askfootage.ports.perception import PerceptionError
from askfootage.settings import Settings

WAITING = "rec-1030-1200"
READY = "rec-1030-0800"
PREPARING = "rec-1030-1000"
LEAKY_TEXT = f"C:\\Users\\someone\\models\\sam.bin refused key={FAKE_KEY}"


class HeldJobs:
    """A scheduler that keeps each job until the test runs it."""

    def __init__(self) -> None:
        self.jobs: list[Callable[[], None]] = []

    def __call__(self, tasks: BackgroundTasks, job: Callable[[], None]) -> None:
        self.jobs.append(job)

    def run_all(self) -> None:
        """Run and forget every held job, in order."""
        jobs, self.jobs = self.jobs, []
        for job in jobs:
            job()


def _pipeline(store: InMemoryLibrary, perception: FakePerception | None = None) -> IndexingPipeline:
    return IndexingPipeline(
        perception=perception or FakePerception({"person": [make_track(0, "person", [0, 1, 2])]}),
        preparer=FakePreparer(),
        layout=FakeLayout(),
        tracks=InMemoryTrackStore(store),
        nouns=("person",),
        source_for=lambda recording: Path(FAKE_SERVER_ROOT / "uploads" / f"{recording.id}.mp4"),
    )


@pytest.fixture
def held() -> HeldJobs:
    """The scheduler the indexing client uses."""
    return HeldJobs()


@pytest.fixture
def indexing_client(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path, held: HeldJobs
) -> Iterator[TestClient]:
    """A client whose app has a working pipeline and holds the work back."""
    app = build_app(
        store, fake_settings, videos_dir, indexing=_pipeline(store), schedule_after_reply=held
    )
    with TestClient(app) as client:
        yield client


def _index(client: TestClient, recording_id: str) -> httpx.Response:
    return client.post(f"/api/recordings/{recording_id}/index")


def _status(client: TestClient, recording_id: str, day: str = "2026-10-30") -> str:
    recordings = client.get("/api/recordings", params={"day": day}).json()
    return next(found["status"] for found in recordings if found["id"] == recording_id)


def _assert_no_leaks(response: httpx.Response) -> None:
    text = response.text + "\n".join(f"{k}: {v}" for k, v in response.headers.items())
    for needle in (FAKE_KEY, "sk-test", "C:\\Users", str(FAKE_SERVER_ROOT), "Traceback"):
        assert needle not in text


# --- Not configured (the default build) -----------------------------------------------------


def test_the_default_build_answers_503_and_changes_nothing(
    client: TestClient, store: InMemoryLibrary
) -> None:
    before = dict(store.recordings)
    response = _index(client, WAITING)
    message = assert_error(response, 503, "indexing_not_configured")
    assert message == "Indexing is not configured in this build"
    assert response.json() == load_example("index-not-configured.json")
    assert store.recordings == before and store.status_log == []
    assert _status(client, WAITING) == "waiting"


@pytest.mark.parametrize("recording_id", [READY, "rec-nope"])
def test_the_default_build_answers_503_for_any_valid_id(
    client: TestClient, recording_id: str
) -> None:
    assert_error(_index(client, recording_id), 503, "indexing_not_configured")


def test_503_does_not_touch_the_store(fake_settings: Settings, videos_dir: Path) -> None:
    store = ExplodingLibrary(FAKE_KEY)
    with TestClient(build_app(store, fake_settings, videos_dir)) as client:
        response = _index(client, WAITING)
    assert_error(response, 503, "indexing_not_configured")
    _assert_no_leaks(response)


# --- Accepted -------------------------------------------------------------------------------


def test_a_waiting_recording_is_accepted_and_preparing_at_reply_time(
    indexing_client: TestClient, held: HeldJobs, store: InMemoryLibrary
) -> None:
    response = _index(indexing_client, WAITING)
    assert response.status_code == 202, response.text
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"id": WAITING, "status": "preparing"}
    assert _status(indexing_client, WAITING) == "preparing"
    assert len(held.jobs) == 1

    held.run_all()
    assert _status(indexing_client, WAITING) == "ready"
    assert [status for rid, status, _ in store.status_log if rid == WAITING] == [
        "preparing",
        "indexing",
        "ready",
    ]


def test_the_accepted_body_matches_the_contract_example(
    indexing_client: TestClient, store: InMemoryLibrary
) -> None:
    example = load_example("index-accepted.json")
    assert set(example) == set(_index(indexing_client, WAITING).json()) == {"id", "status"}
    assert example["status"] == "preparing"


def test_by_default_the_work_runs_after_the_reply(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    app = build_app(store, fake_settings, videos_dir, indexing=_pipeline(store))
    with TestClient(app) as client:
        response = _index(client, WAITING)
        assert response.status_code == 202
        assert response.json() == {"id": WAITING, "status": "preparing"}
        # TestClient returns once the background work has finished.
        assert _status(client, WAITING) == "ready"


def test_the_ui_can_start_indexing_across_origins(indexing_client: TestClient) -> None:
    response = indexing_client.post(
        f"/api/recordings/{WAITING}/index", headers={"Origin": UI_ORIGIN}
    )
    assert response.status_code == 202
    assert response.headers["access-control-allow-origin"] == UI_ORIGIN


# --- Refused --------------------------------------------------------------------------------


def test_an_unknown_recording_is_404(indexing_client: TestClient, held: HeldJobs) -> None:
    assert_error(_index(indexing_client, "rec-nope"), 404, "not_found")
    assert held.jobs == []


@pytest.mark.parametrize(
    ("recording_id", "day"), [(READY, "2026-10-30"), (PREPARING, "2026-10-30")]
)
def test_a_recording_that_is_not_waiting_is_409(
    indexing_client: TestClient, held: HeldJobs, recording_id: str, day: str
) -> None:
    before = _status(indexing_client, recording_id, day)
    assert_error(_index(indexing_client, recording_id), 409, "recording_not_waiting")
    assert _status(indexing_client, recording_id, day) == before
    assert held.jobs == []


def test_a_second_call_while_the_first_runs_is_409(
    indexing_client: TestClient, held: HeldJobs
) -> None:
    assert _index(indexing_client, WAITING).status_code == 202
    assert_error(_index(indexing_client, WAITING), 409, "recording_not_waiting")
    assert len(held.jobs) == 1


def test_a_finished_recording_cannot_be_indexed_again(
    indexing_client: TestClient, held: HeldJobs
) -> None:
    _index(indexing_client, WAITING)
    held.run_all()
    assert_error(_index(indexing_client, WAITING), 409, "recording_not_waiting")


@pytest.mark.parametrize("bad_id", ["bad.id", "x" * 65, "rec%20one"])
def test_a_bad_id_is_422(indexing_client: TestClient, held: HeldJobs, bad_id: str) -> None:
    message = assert_error(_index(indexing_client, bad_id), 422, "validation_error")
    assert message == "id: must be 1 to 64 letters, digits, '-' or '_'"
    assert held.jobs == []


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_other_methods_are_405(indexing_client: TestClient, method: str) -> None:
    response = indexing_client.request(method, f"/api/recordings/{WAITING}/index")
    assert_error(response, 405, "method_not_allowed")


def test_a_store_failure_is_a_bare_500(
    fake_settings: Settings, videos_dir: Path, held: HeldJobs
) -> None:
    store = ExplodingLibrary(FAKE_KEY)
    app = build_app(
        store, fake_settings, videos_dir, indexing=_pipeline(store), schedule_after_reply=held
    )
    with TestClient(app) as client:
        response = _index(client, WAITING)
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Something went wrong."}
    }
    assert response.status_code == 500
    _assert_no_leaks(response)
    assert held.jobs == []


# --- Failure after the reply ------------------------------------------------------------------


def test_a_failure_after_the_reply_goes_back_to_waiting_and_can_be_retried(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path, held: HeldJobs
) -> None:
    perception = FakePerception(error=PerceptionError(LEAKY_TEXT))
    app = build_app(
        store,
        fake_settings,
        videos_dir,
        indexing=_pipeline(store, perception),
        schedule_after_reply=held,
    )
    with TestClient(app) as client:
        assert _index(client, WAITING).status_code == 202
        held.run_all()
        assert _status(client, WAITING) == "waiting"
        listed = client.get("/api/recordings", params={"day": "2026-10-30"})
        _assert_no_leaks(listed)
        assert all(
            set(found) == {"id", "camera", "day", "startTime", "lengthSeconds", "status"}
            for found in listed.json()
        )
        note = store.recordings[WAITING].status_note
        assert note and FAKE_KEY not in note and "C:\\Users" not in note

        perception.error = None
        assert _index(client, WAITING).status_code == 202
        held.run_all()
        assert _status(client, WAITING) == "ready"
        assert store.recordings[WAITING].status_note is None


def test_responses_never_leak_on_any_outcome(indexing_client: TestClient, held: HeldJobs) -> None:
    for recording_id in (WAITING, WAITING, READY, "rec-nope", "bad.id"):
        _assert_no_leaks(_index(indexing_client, recording_id))
    held.run_all()
