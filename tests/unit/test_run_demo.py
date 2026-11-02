"""scripts.run_demo: the checks and message paths, with temporary folders and no network."""

import io
import json
from pathlib import Path

from scripts import ingest_real_clips, run_demo

HEX = "0" * 64


def run(root: Path, *argv: str, which=lambda name: f"/fake/{name}"):  # noqa: ANN001, ANN201
    out = io.StringIO()
    served: list[tuple[Path, int]] = []
    code = run_demo.main(
        list(argv), root=root, out=out, serve=lambda r, p: served.append((r, p)), which=which
    )
    return code, out.getvalue(), served


def put_videos(root: Path) -> None:
    (root / "videos").mkdir(parents=True, exist_ok=True)
    for clip in ("clip1", "clip2"):
        (root / "videos" / f"{clip}.mp4").write_bytes(b"x")


def put_manifest(root: Path) -> None:
    folder = root / "demo" / "sam"
    folder.mkdir(parents=True, exist_ok=True)
    clips = {clip: {"prepared_sha256": HEX} for clip in ("clip1", "clip2")}
    (folder / "manifest.json").write_text(json.dumps({"clips": clips}), encoding="utf-8")


def test_missing_videos_are_named_with_where_to_put_them(tmp_path: Path) -> None:
    code, text, served = run(tmp_path)
    assert code == 2 and served == []
    assert "clip1.mp4 and clip2.mp4 not found" in text
    assert str(tmp_path / "videos" / "clip1.mp4") in text
    assert "nothing can play" in text
    assert "Traceback" not in text


def test_one_missing_video_is_named_alone(tmp_path: Path) -> None:
    put_videos(tmp_path)
    (tmp_path / "videos" / "clip2.mp4").unlink()
    code, text, _ = run(tmp_path)
    assert code == 2 and "clip2.mp4 not found" in text and "clip1.mp4 not found" not in text


def test_missing_ffmpeg_is_explained(tmp_path: Path) -> None:
    put_videos(tmp_path)
    code, text, served = run(tmp_path, which=lambda name: None)
    assert code == 2 and served == []
    assert "ffmpeg and ffprobe not found on PATH" in text and "ffmpeg -version" in text


def test_missing_replies_are_explained(tmp_path: Path) -> None:
    put_videos(tmp_path)
    for clip in ("clip1", "clip2"):
        prepared = tmp_path / "data" / "prepared" / clip
        prepared.mkdir(parents=True)
        (prepared / "prepared.mp4").write_bytes(b"x")
    code, text, served = run(tmp_path)
    assert code == 2 and served == []
    assert "saved replies were not found" in text and "git checkout -- demo/sam" in text


def test_different_prepared_bytes_are_reported_with_the_hint(tmp_path: Path) -> None:
    put_videos(tmp_path)
    put_manifest(tmp_path)
    for clip in ("clip1", "clip2"):
        prepared = tmp_path / "data" / "prepared" / clip
        prepared.mkdir(parents=True)
        (prepared / "prepared.mp4").write_bytes(b"other bytes")
    code, text, served = run(tmp_path)
    assert code == 2 and served == []
    assert "clip1, clip2 differs" in text and "sha256 does not match" in text
    assert "Remove-Item -Recurse" in text and "ffmpeg 8.x" in text


def test_ready_data_skips_the_steps_and_serves_with_web_commands(tmp_path: Path) -> None:
    put_videos(tmp_path)
    data = tmp_path / "data" / "real"
    data.mkdir(parents=True)
    (data / ingest_real_clips.LIBRARY_NAME).write_bytes(b"")
    for clip in ("clip1", "clip2"):
        (data / clip).mkdir()
        (data / clip / "prepared.mp4").write_bytes(b"x")
    assert not run_demo.needs_ingest(tmp_path)
    code, text, served = run(tmp_path, "--port", "8123")
    assert code == 0 and served == [(tmp_path, 8123)]
    assert "http://localhost:8123" in text
    assert "cd web; $env:VITE_API_URL='http://localhost:8123'; npm run dev" in text
    assert "http://localhost:5173" in text
    assert "Preparing" not in text


def test_default_port_is_8000(tmp_path: Path) -> None:
    put_videos(tmp_path)
    data = tmp_path / "data" / "real"
    data.mkdir(parents=True)
    (data / ingest_real_clips.LIBRARY_NAME).write_bytes(b"")
    for clip in ("clip1", "clip2"):
        (data / clip).mkdir()
        (data / clip / "prepared.mp4").write_bytes(b"x")
    assert run(tmp_path)[2] == [(tmp_path, 8000)]


def test_missing_library_means_ingest_is_needed(tmp_path: Path) -> None:
    assert run_demo.needs_ingest(tmp_path)
