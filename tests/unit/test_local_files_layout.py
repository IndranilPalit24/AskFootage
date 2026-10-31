"""LocalVideoFiles: where each video's files live, and refusal of ids that could escape."""

import os
import subprocess
from pathlib import Path

import pytest

from askfootage.adapters.storage.local_files import InvalidVideoIdError, LocalVideoFiles
from askfootage.ports.video_store import VideoFileLayout


def test_it_satisfies_the_layout_port(tmp_path: Path) -> None:
    layout: VideoFileLayout = LocalVideoFiles(tmp_path)
    assert isinstance(layout, LocalVideoFiles)


def test_video_dir_is_the_id_folder_under_the_data_dir_and_is_created(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    folder = LocalVideoFiles(data_dir).video_dir("rec_01-A")

    assert folder == data_dir.resolve() / "rec_01-A"
    assert folder.is_dir()


def test_raw_dir_is_the_raw_folder_inside_the_video_folder_and_is_created(tmp_path: Path) -> None:
    raw = LocalVideoFiles(tmp_path).raw_dir("rec1")

    assert raw == tmp_path.resolve() / "rec1" / "raw"
    assert raw.is_dir()


def test_prepared_path_is_prepared_mp4_inside_the_video_folder(tmp_path: Path) -> None:
    prepared = LocalVideoFiles(tmp_path).prepared_path("rec1")

    assert prepared == tmp_path.resolve() / "rec1" / "prepared.mp4"
    assert prepared.parent.is_dir()
    assert not prepared.exists()


def test_a_relative_data_dir_is_anchored_once_at_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    layout = LocalVideoFiles(Path("data"))
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")

    assert layout.video_dir("rec1") == tmp_path.resolve() / "data" / "rec1"


def test_the_longest_allowed_id_is_accepted(tmp_path: Path) -> None:
    video_id = "a" * 64
    assert LocalVideoFiles(tmp_path).video_dir(video_id).name == video_id


BAD_IDS = [
    "",
    "..",
    ".",
    "../x",
    "..\\x",
    "a/b",
    "a\\b",
    "/abs",
    "\\abs",
    "C:x",
    "C:\\x",
    "C:",
    "a" * 65,
    "rec 1",
    "rec.1",
    "rec1\n",
    "rec1\x00",
    "réc",
    "~",
    "CON",
    "nul",
    "Com1",
    "LPT9",
]


@pytest.mark.parametrize("video_id", BAD_IDS, ids=repr)
@pytest.mark.parametrize("method", ["video_dir", "raw_dir", "prepared_path"])
def test_unsafe_ids_are_refused_by_every_method(tmp_path: Path, method: str, video_id: str) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    before = set(tmp_path.rglob("*"))

    with pytest.raises(InvalidVideoIdError):
        getattr(LocalVideoFiles(data_dir), method)(video_id)

    assert set(tmp_path.rglob("*")) == before


def test_a_non_string_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InvalidVideoIdError):
        LocalVideoFiles(tmp_path).video_dir(123)  # type: ignore[arg-type]


def test_the_refusal_message_does_not_echo_the_id_or_the_data_dir(tmp_path: Path) -> None:
    with pytest.raises(InvalidVideoIdError) as caught:
        LocalVideoFiles(tmp_path).video_dir("../escape-attempt")

    assert "escape-attempt" not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


def test_an_invalid_id_error_is_a_value_error() -> None:
    assert issubclass(InvalidVideoIdError, ValueError)


@pytest.mark.parametrize("video_id", ["../x", "..\\x", "a/b", "C:x", "/abs", "", "a" * 65])
def test_ids_with_path_syntax_are_refused_by_the_character_rule(
    tmp_path: Path, video_id: str
) -> None:
    with pytest.raises(InvalidVideoIdError, match="letters, digits"):
        LocalVideoFiles(tmp_path).video_dir(video_id)


def _link_folder(link: Path, target: Path) -> None:
    """Make link point at target: a symlink, or on Windows a junction when symlinks are off."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError:
        if os.name != "nt":
            pytest.skip("this system does not allow creating symlinks")
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
        timeout=30,
    )


def test_a_video_folder_that_links_outside_the_data_dir_is_refused(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _link_folder(data_dir / "rec1", outside)

    for method in ("video_dir", "raw_dir", "prepared_path"):
        with pytest.raises(InvalidVideoIdError, match="outside the data folder"):
            getattr(LocalVideoFiles(data_dir), method)("rec1")
    assert list(outside.iterdir()) == []


def test_peek_methods_validate_but_never_create_folders(tmp_path: Path) -> None:
    files = LocalVideoFiles(tmp_path)
    assert files.peek_dir("ghost") == tmp_path.resolve() / "ghost"
    assert files.peek_prepared("ghost") == tmp_path.resolve() / "ghost" / "prepared.mp4"
    assert list(tmp_path.iterdir()) == []
    for bad in ("..", "a/b", "con", ""):
        with pytest.raises(InvalidVideoIdError):
            files.peek_dir(bad)
