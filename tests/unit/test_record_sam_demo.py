"""scripts.record_sam_demo: turn the saved real SAM replies into small, key-free recordings.

The script reads the replies the spike saved (data/spike/sam_<clip>_<noun>.json), rebuilds
the exact requests that produced them and saves each reply, masks stripped, under the
request's fingerprint, so ReplayTransport answers the same request with no key or network.
Nothing here calls Meta.
"""

import hashlib
import io
import json
from pathlib import Path

import pytest

from askfootage.adapters.meta.record_replay import ReplayTransport, fingerprint
from askfootage.adapters.meta.sam import parse_sam_stream, sam_request, upload_request, video_part
from scripts import record_sam_demo

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "sam"
VIDEO_BYTES = b"pretend this is a 5 fps video"


def files_reply(file_id: str, size: int) -> str:
    return json.dumps(
        {
            "id": file_id,
            "bytes": size,
            "object": "file",
            "purpose": "user_data",
            "status": "uploaded",
        }
    )


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    spike = tmp_path / "spike"
    prepared = tmp_path / "prepared"
    spike.mkdir()
    for clip, noun, fixture in (
        ("clip1", "hand", "clip1_hand_with_masks.sse"),
        ("clip1", "box", "clip1_box_empty.sse"),
        ("clip2", "box", "clip2_box_head.sse"),
    ):
        (prepared / clip).mkdir(parents=True, exist_ok=True)
        (prepared / clip / "prepared.mp4").write_bytes(VIDEO_BYTES + clip.encode())
        envelope = {
            "clip": clip,
            "concept": noun,
            "http_status": 200,
            "files_reply": files_reply(f"file-{clip}", len(VIDEO_BYTES + clip.encode())),
            "raw": (FIXTURES / fixture).read_text(encoding="utf-8"),
        }
        (spike / f"sam_{clip}_{noun}.json").write_text(json.dumps(envelope, indent=2))
    return {"spike": spike, "prepared": prepared, "out": tmp_path / "demo" / "sam"}


def run(workspace: dict[str, Path], *extra: str) -> tuple[int, str]:
    out = io.StringIO()
    code = record_sam_demo.main(
        [
            "--spike-dir",
            str(workspace["spike"]),
            "--prepared-dir",
            str(workspace["prepared"]),
            "--out",
            str(workspace["out"]),
            *extra,
        ],
        out=out,
    )
    return code, out.getvalue()


def test_every_reply_and_upload_is_recorded(workspace: dict[str, Path]) -> None:
    code, _ = run(workspace)
    assert code == 0
    names = sorted(p.name for p in workspace["out"].glob("*.json"))
    assert len(names) == 3 + 2 + 1  # three replies, two uploads, one manifest


def test_no_mask_is_left_in_any_recording(workspace: dict[str, Path]) -> None:
    run(workspace)
    for path in workspace["out"].glob("*.json"):
        assert "<|mask" not in path.read_text(encoding="utf-8")


def test_each_recording_is_small(workspace: dict[str, Path]) -> None:
    run(workspace)
    for path in workspace["out"].glob("*.json"):
        assert path.stat().st_size < record_sam_demo.MAX_RECORDING_BYTES


def test_replay_answers_the_same_requests_with_the_same_detections(
    workspace: dict[str, Path],
) -> None:
    run(workspace)
    replay = ReplayTransport(workspace["out"])
    video = workspace["prepared"] / "clip2" / "prepared.mp4"
    assert replay.send(upload_request(video)).body == files_reply(
        "file-clip2", video.stat().st_size
    )
    reply = replay.send(sam_request("box", video_part("file-clip2")))
    assert [d.frame for d in parse_sam_stream(reply.body)] == [6, 7, 8]


def test_the_recordings_are_named_by_the_fingerprint_of_the_real_request(
    workspace: dict[str, Path],
) -> None:
    run(workspace)
    request = sam_request("hand", video_part("file-clip1"))
    assert (workspace["out"] / f"{fingerprint(request)}.json").is_file()


def test_the_manifest_lists_each_clip_its_video_hash_and_its_requests(
    workspace: dict[str, Path],
) -> None:
    run(workspace)
    manifest = json.loads((workspace["out"] / "manifest.json").read_text(encoding="utf-8"))
    video = workspace["prepared"] / "clip1" / "prepared.mp4"
    clip = manifest["clips"]["clip1"]
    assert clip["prepared_sha256"] == hashlib.sha256(video.read_bytes()).hexdigest()
    assert clip["file_id"] == "file-clip1"
    assert clip["upload_fingerprint"] == fingerprint(upload_request(video))
    assert set(clip["requests"]) == {"hand", "box"}
    assert clip["requests"]["hand"]["fingerprint"] == fingerprint(
        sam_request("hand", video_part("file-clip1"))
    )
    assert clip["requests"]["hand"]["detections"] == 3
    assert clip["requests"]["box"]["detections"] == 0
    assert manifest["model"] == "sam-3.1"


def test_running_twice_changes_nothing(workspace: dict[str, Path]) -> None:
    run(workspace)
    before = {p.name: p.read_bytes() for p in workspace["out"].glob("*.json")}
    code, _ = run(workspace)
    assert code == 0
    assert {p.name: p.read_bytes() for p in workspace["out"].glob("*.json")} == before


def test_a_missing_prepared_video_is_refused(workspace: dict[str, Path]) -> None:
    (workspace["prepared"] / "clip2" / "prepared.mp4").unlink()
    code, text = run(workspace)
    assert code == 2
    assert "clip2" in text


def test_a_prepared_video_that_is_not_the_uploaded_file_is_refused(
    workspace: dict[str, Path],
) -> None:
    (workspace["prepared"] / "clip1" / "prepared.mp4").write_bytes(b"re-encoded since")
    code, text = run(workspace)
    assert code == 2
    assert "clip1" in text and "bytes" in text
    assert not list(workspace["out"].glob("*.json")) if workspace["out"].exists() else True


def test_a_spike_folder_with_no_replies_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    out = io.StringIO()
    code = record_sam_demo.main(
        ["--spike-dir", str(empty), "--prepared-dir", str(empty), "--out", str(tmp_path / "o")],
        out=out,
    )
    assert code == 2


def test_a_damaged_reply_is_refused_and_nothing_is_saved(workspace: dict[str, Path]) -> None:
    path = workspace["spike"] / "sam_clip2_box.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["raw"] = envelope["raw"][:300]
    path.write_text(json.dumps(envelope))
    code, text = run(workspace)
    assert code == 2
    assert "sam_clip2_box.json" in text
    assert "<|" not in text


def test_the_output_names_each_file_and_its_size(workspace: dict[str, Path]) -> None:
    _, text = run(workspace)
    assert "clip1" in text and "hand" in text and "KB" in text
