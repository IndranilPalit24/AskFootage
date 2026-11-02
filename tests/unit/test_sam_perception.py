"""SamPerception: upload once, ask once per noun, parse the reply into tracks.

Every test runs on a stand-in transport or a ReplayTransport; nothing here has a key or a
network.
"""

import json
from pathlib import Path

import pytest

from askfootage.adapters.meta.record_replay import (
    RecordingTransport,
    ReplayTransport,
    fingerprint,
)
from askfootage.adapters.meta.sam import (
    SamPerception,
    SamStreamError,
    redact_sam_reply,
    sam_request,
    upload_request,
    video_part,
)
from askfootage.adapters.meta.transport import (
    MetaApiError,
    MetaConnectionError,
    MetaRequest,
    RawResponse,
    RecordingNotFoundError,
)
from askfootage.ports.perception import PerceptionError, PerceptionNotSentError
from askfootage.settings import MissingApiKeyError

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "sam"
FILES_REPLY = json.dumps({"id": "file-123", "bytes": 5, "object": "file", "status": "uploaded"})


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class Stub:
    """A transport that answers /files with a file id and /responses from a table."""

    def __init__(self, replies: dict[str, str] | None = None) -> None:
        self.replies = replies or {}
        self.sent: list[MetaRequest] = []

    def send(self, request: MetaRequest) -> RawResponse:
        self.sent.append(request)
        if request.path == "/files":
            return RawResponse(200, FILES_REPLY)
        assert request.json_body is not None
        prompt = request.json_body["input"][0]["content"][0]["text"]
        return RawResponse(200, self.replies[prompt])


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "prepared.mp4"
    path.write_bytes(b"not really a video")
    return path


def test_finds_tracks_labelled_with_the_noun(video: Path) -> None:
    perception = SamPerception(Stub({"hand": fixture("clip1_hand_two_objects.sse")}))
    tracks = perception.detect_and_track(video, "hand")
    assert [(t.track_id, t.label) for t in tracks] == [(0, "hand"), (1, "hand")]


def test_uploads_the_video_once_for_every_noun(video: Path) -> None:
    stub = Stub({"hand": fixture("clip1_box_empty.sse"), "person": fixture("clip1_box_empty.sse")})
    perception = SamPerception(stub)
    perception.detect_and_track(video, "hand")
    perception.detect_and_track(video, "person")
    assert [r.path for r in stub.sent] == ["/files", "/responses", "/responses"]


def test_the_request_names_the_uploaded_file_and_asks_for_confidence(video: Path) -> None:
    stub = Stub({"hand": fixture("clip1_box_empty.sse")})
    SamPerception(stub).detect_and_track(video, "hand")
    assert stub.sent[1] == sam_request("hand", video_part("file-123"))
    body = stub.sent[1].json_body
    assert body is not None
    assert body["model"] == "sam-3.1" and body["stream"] is True
    assert body["metadata"] == {"include_confidence": "true"}


def test_a_cardboard_box_is_asked_for_as_box_but_keeps_its_label(video: Path) -> None:
    stub = Stub({"box": fixture("clip2_box_head.sse")})
    (track,) = SamPerception(stub).detect_and_track(video, "cardboard box")
    assert track.label == "cardboard box"
    assert stub.sent[1] == sam_request("box", video_part("file-123"))


def test_nothing_found_is_an_empty_list(video: Path) -> None:
    stub = Stub({"box": fixture("clip1_box_empty.sse")})
    assert SamPerception(stub).detect_and_track(video, "box") == []


def test_a_missing_video_is_refused_before_anything_is_sent(tmp_path: Path) -> None:
    stub = Stub()
    with pytest.raises(PerceptionNotSentError):
        SamPerception(stub).detect_and_track(tmp_path / "nope.mp4", "person")
    assert stub.sent == []


class Failing:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def send(self, request: MetaRequest) -> RawResponse:
        raise self.error


def test_a_missing_key_counts_as_not_sent(video: Path) -> None:
    with pytest.raises(PerceptionNotSentError):
        SamPerception(Failing(MissingApiKeyError("no key"))).detect_and_track(video, "person")


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (MetaApiError(429, "slow down SECRET-BODY"), "HTTP 429"),
        (MetaConnectionError("could not connect to /home/me/x"), "could not be reached"),
        (RecordingNotFoundError("no recording in C:\\hidden\\dir"), "No saved reply"),
    ],
)
def test_transport_failures_become_safe_perception_errors(
    video: Path, error: Exception, shown: str
) -> None:
    with pytest.raises(PerceptionError) as caught:
        SamPerception(Failing(error)).detect_and_track(video, "person")
    assert shown in str(caught.value)
    assert "SECRET" not in str(caught.value) and "hidden" not in str(caught.value)
    assert not isinstance(caught.value, PerceptionNotSentError)


def test_an_upload_reply_without_an_id_is_an_error(video: Path) -> None:
    class NoId(Stub):
        def send(self, request: MetaRequest) -> RawResponse:
            return RawResponse(200, "{}") if request.path == "/files" else super().send(request)

    with pytest.raises(PerceptionError, match="file id"):
        SamPerception(NoId()).detect_and_track(video, "person")


def test_a_damaged_reply_is_a_stream_error(video: Path) -> None:
    full = fixture("clip2_box_head.sse")
    stub = Stub({"person": full[: full.index("event: response.completed")]})
    with pytest.raises(SamStreamError):
        SamPerception(stub).detect_and_track(video, "person")


class TestRecordThenReplay:
    def test_a_recorded_reply_is_saved_without_masks_and_replays_to_the_same_tracks(
        self, video: Path, tmp_path: Path
    ) -> None:
        saved = tmp_path / "saved"
        live = Stub({"hand": fixture("clip1_hand_with_masks.sse")})
        recording = RecordingTransport(live, saved, redact=redact_sam_reply)
        first = SamPerception(recording).detect_and_track(video, "hand")

        files = sorted(saved.glob("*.json"))
        assert len(files) == 2  # the upload and the reply
        text = "".join(f.read_text(encoding="utf-8") for f in files)
        assert "<|mask" not in text

        replayed = SamPerception(ReplayTransport(saved)).detect_and_track(video, "hand")
        assert replayed == first

    def test_the_stripped_recording_keeps_the_fingerprint_of_the_real_request(
        self, video: Path, tmp_path: Path
    ) -> None:
        saved = tmp_path / "saved"
        recording = RecordingTransport(
            Stub({"hand": fixture("clip1_hand_with_masks.sse")}), saved, redact=redact_sam_reply
        )
        SamPerception(recording).detect_and_track(video, "hand")
        request = sam_request("hand", video_part("file-123"))
        assert (saved / f"{fingerprint(request)}.json").is_file()
        assert (saved / f"{fingerprint(upload_request(video))}.json").is_file()
        assert ReplayTransport(saved).send(request).status == 200

    def test_the_caller_still_receives_the_full_reply(self, video: Path, tmp_path: Path) -> None:
        full = fixture("clip1_hand_with_masks.sse")
        recording = RecordingTransport(
            Stub({"hand": full}), tmp_path / "saved", redact=redact_sam_reply
        )
        assert recording.send(sam_request("hand", video_part("file-123"))).body == full

    def test_a_file_reply_is_saved_as_it_is(self, video: Path, tmp_path: Path) -> None:
        saved = tmp_path / "saved"
        RecordingTransport(Stub(), saved, redact=redact_sam_reply).send(upload_request(video))
        recording = saved / f"{fingerprint(upload_request(video))}.json"
        assert json.loads(recording.read_text(encoding="utf-8"))["body"] == FILES_REPLY

    def test_an_unreadable_reply_is_not_saved(self, video: Path, tmp_path: Path) -> None:
        saved = tmp_path / "saved"
        recording = RecordingTransport(Stub({"hand": "garbage"}), saved, redact=redact_sam_reply)
        with pytest.raises(SamStreamError):
            recording.send(sam_request("hand", video_part("file-123")))
        assert not list(saved.glob("*.json"))
