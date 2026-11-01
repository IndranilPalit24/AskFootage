"""scripts.ingest_real_clips: both real clips into SQLite, offline, from the saved SAM replies.

The perception is a ReplayTransport (or here a stand-in transport), the preparer only copies
and probes, and nothing reads settings or a key. Every test uses a temporary folder.
"""

import io
import json
import re
from datetime import date
from pathlib import Path

import pytest

from askfootage.adapters.media.ffmpeg import CommandResult, PreparedCopyPreparer
from askfootage.adapters.meta.sam import SAM_MODEL
from askfootage.adapters.meta.transport import MetaRequest, RawResponse
from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.adapters.sqlite.tracks import SqliteTrackStore
from scripts import ingest_real_clips

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "sam"
REPLIES = {
    "person": "clip2_person_id_break.sse",
    "box": "clip2_box_head.sse",
    "hand": "clip1_hand_two_objects.sse",
}


class Stub:
    """Answers /files with an id and /responses with a fixture chosen by the prompt."""

    def __init__(self) -> None:
        self.sent: list[MetaRequest] = []

    def send(self, request: MetaRequest) -> RawResponse:
        self.sent.append(request)
        if request.path == "/files":
            return RawResponse(200, json.dumps({"id": "file-1"}))
        assert request.json_body is not None and request.json_body["model"] == SAM_MODEL
        prompt = request.json_body["input"][0]["content"][0]["text"]
        return RawResponse(200, (FIXTURES / REPLIES[prompt]).read_text(encoding="utf-8"))


def fake_probe(args: list[str], *, timeout: float) -> CommandResult:
    stream = {"nb_frames": "47", "duration": "9.4", "width": 1920, "height": 1080}
    return CommandResult(0, json.dumps({"streams": [stream], "format": {"duration": "9.4"}}), "")


@pytest.fixture
def folders(tmp_path: Path) -> dict[str, Path]:
    prepared = tmp_path / "prepared"
    for clip in ("clip1", "clip2"):
        (prepared / clip).mkdir(parents=True)
        (prepared / clip / "prepared.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + clip.encode())
    return {"prepared": prepared, "data": tmp_path / "real", "replies": tmp_path / "unused"}


def run(folders: dict[str, Path], stub: Stub | None = None, *extra: str) -> tuple[int, str, Stub]:
    stub = stub or Stub()
    out = io.StringIO()
    code = ingest_real_clips.main(
        [
            "--data-dir",
            str(folders["data"]),
            "--prepared-dir",
            str(folders["prepared"]),
            "--recordings-dir",
            str(folders["replies"]),
            *extra,
        ],
        transport=stub,
        preparer=PreparedCopyPreparer(runner=fake_probe, which=lambda name: f"/fake/{name}"),
        out=out,
    )
    return code, out.getvalue(), stub


def stores(folders: dict[str, Path]) -> tuple[SqliteLibraryStore, SqliteTrackStore]:
    library = SqliteLibraryStore(folders["data"] / ingest_real_clips.LIBRARY_NAME)
    return library, SqliteTrackStore(library)


def test_both_clips_become_ready_recordings_of_one_camera(folders: dict[str, Path]) -> None:
    code, _, _ = run(folders)
    assert code == 0
    library, _ = stores(folders)
    found = library.list_recordings(None, ingest_real_clips.DEFAULT_DAY)
    assert [(r.id, r.camera, r.status) for r in found] == [
        ("clip1", "CAM-001", "ready"),
        ("clip2", "CAM-001", "ready"),
    ]
    assert all(r.length_seconds == 10 for r in found)  # 9.4 s, rounded up


def test_tracks_are_stored_per_noun_with_the_vocabulary_label(folders: dict[str, Path]) -> None:
    run(folders)
    _, tracks = stores(folders)
    assert [t.track_id for t in tracks.tracks_for("clip2", "person")] == [0, 2, 3, 4]
    (box,) = tracks.tracks_for("clip2", "cardboard box")
    assert box.frames == (6, 7, 8)
    assert [t.track_id for t in tracks.tracks_for("clip1", "hand")] == [0, 1]


def test_the_prepared_copy_is_made_where_the_layout_keeps_it(folders: dict[str, Path]) -> None:
    run(folders)
    copy = folders["data"] / "clip1" / "prepared.mp4"
    assert copy.read_bytes() == (folders["prepared"] / "clip1" / "prepared.mp4").read_bytes()


def test_each_clip_is_uploaded_once_and_each_noun_asked_once(folders: dict[str, Path]) -> None:
    _, _, stub = run(folders)
    assert [r.path for r in stub.sent].count("/files") == 2
    assert [r.path for r in stub.sent].count("/responses") == 6


def table(text: str) -> dict[tuple[str, str], dict[str, str]]:
    """The printed table as {(clip, noun): {column: cell}}; cells are separated by 2+ spaces."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("clip "))
    columns = re.split(r"\s{2,}", lines[start].strip())
    rows = {}
    for line in lines[start + 1 : start + 7]:
        cells = re.split(r"\s{2,}", line.strip())
        rows[(cells[0], cells[1])] = dict(zip(columns, cells, strict=True))
    return rows


def test_a_table_lists_tracks_per_clip_and_noun(folders: dict[str, Path]) -> None:
    _, text, _ = run(folders)
    rows = table(text)
    assert set(rows) == {
        (c, n) for c in ("clip1", "clip2") for n in ("person", "cardboard box", "hand")
    }
    box = rows[("clip2", "cardboard box")]
    assert (box["raw"], box["stored"], box["ids"], box["frames"], box["seconds"]) == (
        "1",
        "1",
        "0",
        "6-8",
        "1.2-1.6",
    )


def test_the_table_shows_ids_that_stitching_left_alone(folders: dict[str, Path]) -> None:
    _, text, _ = run(folders)
    person = table(text)[("clip2", "person")]
    assert (person["raw"], person["stored"], person["ids"]) == ("4", "4", "0,2,3,4")


def test_the_table_has_a_dash_for_a_noun_that_found_nothing(folders: dict[str, Path]) -> None:
    class Empty(Stub):
        def send(self, request: MetaRequest) -> RawResponse:
            if request.path == "/responses":
                return RawResponse(
                    200, (FIXTURES / "clip1_box_empty.sse").read_text(encoding="utf-8")
                )
            return super().send(request)

    _, text, _ = run(folders, Empty())
    assert table(text)[("clip1", "person")]["stored"] == "0"
    assert table(text)[("clip1", "person")]["frames"] == "-"


def test_running_again_changes_nothing_and_does_not_fail(folders: dict[str, Path]) -> None:
    run(folders)
    _, first = stores(folders)
    before = {noun: first.tracks_for("clip2", noun) for noun in ("person", "cardboard box", "hand")}
    code, _, _ = run(folders)
    assert code == 0
    _, again = stores(folders)
    assert {n: again.tracks_for("clip2", n) for n in before} == before


def test_a_missing_prepared_video_is_refused_and_nothing_is_created(
    folders: dict[str, Path],
) -> None:
    (folders["prepared"] / "clip2" / "prepared.mp4").unlink()
    code, text, stub = run(folders)
    assert code == 2
    assert "clip2" in text
    assert stub.sent == []


def test_no_setting_or_key_is_read(
    folders: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> None:
        raise AssertionError("settings were read")

    monkeypatch.setattr("askfootage.settings.load_settings", refuse, raising=True)
    assert run(folders)[0] == 0


def test_the_default_day_is_the_demo_day() -> None:
    assert ingest_real_clips.DEFAULT_DAY == date(2026, 10, 30)
