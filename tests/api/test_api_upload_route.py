"""POST /api/recordings: a multipart MP4 upload is checked, dropped and registered.

The limit is 200 MiB; tests that need to cross it use an app built with a 1 KiB limit, or
declare a Content-Length over 200 MiB without sending that much.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from api_fakes import FAKE_MP4, InMemoryLibrary, load_example
from api_support import assert_error, build_app
from fastapi.testclient import TestClient

from askfootage.interfaces.api.upload import FORM_OVERHEAD_BYTES, MAX_UPLOAD_BYTES
from askfootage.settings import Settings

FRIDAY = "2026-10-30"
BOUNDARY = "askfootage-test-boundary"
MULTIPART = f"multipart/form-data; boundary={BOUNDARY}"
SMALL_LIMIT = 1024


def multipart(*parts: tuple[str, str | None, str | None, bytes], close: bool = True) -> bytes:
    """A multipart/form-data body from (name, filename, content type, data) parts."""
    body = b""
    for name, filename, content_type, data in parts:
        disposition = f'form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        body += f"--{BOUNDARY}\r\nContent-Disposition: {disposition}\r\n".encode()
        if content_type is not None:
            body += f"Content-Type: {content_type}\r\n".encode()
        body += b"\r\n" + data + b"\r\n"
    if close:
        body += f"--{BOUNDARY}--\r\n".encode()
    return body


def video_part(
    data: bytes = FAKE_MP4, filename: str = "dock.mp4", content_type: str = "video/mp4"
) -> tuple[str, str | None, str | None, bytes]:
    """The file part of an upload."""
    return ("file", filename, content_type, data)


def day_part(day: str = FRIDAY) -> tuple[str, str | None, str | None, bytes]:
    """The day field of an upload."""
    return ("day", None, None, day.encode())


def camera_part(camera: str = "CAM-001") -> tuple[str, str | None, str | None, bytes]:
    """The camera field of an upload: required, it names the camera that recorded the video."""
    return ("camera", None, None, camera.encode())


def upload(client: TestClient, *parts: tuple[str, str | None, str | None, bytes]) -> Any:
    """POST a multipart body built from parts."""
    return client.post(
        "/api/recordings", content=multipart(*parts), headers={"content-type": MULTIPART}
    )


def files_in(directory: Path) -> set[Path]:
    """Every file under a directory."""
    return {path for path in directory.rglob("*") if path.is_file()}


@pytest.fixture
def upload_client(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> Iterator[TestClient]:
    """A client whose new recordings get the id rec-new1, rec-new2, ..."""
    counter = iter(range(1, 100))
    app = build_app(
        store, fake_settings, videos_dir, make_id=lambda prefix: f"{prefix}-new{next(counter)}"
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def small_limit_client(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> Iterator[TestClient]:
    """A client for an app that accepts videos of at most 1 KiB."""
    app = build_app(store, fake_settings, videos_dir, max_upload_bytes=SMALL_LIMIT)
    with TestClient(app) as client:
        yield client


# --- Accepted -----------------------------------------------------------------------------


def test_an_mp4_upload_is_accepted_and_waits(upload_client: TestClient) -> None:
    response = upload_client.post(
        "/api/recordings",
        files={"file": ("dock.mp4", FAKE_MP4, "video/mp4")},
        data={"day": FRIDAY, "camera": "CAM-001"},
    )
    assert response.status_code == 202
    assert response.json() == {"id": "rec-new1", "status": "waiting"}
    assert set(response.json()) == set(load_example("recording-accepted.json"))


def test_the_new_recording_is_listed_and_counted(upload_client: TestClient) -> None:
    upload(upload_client, video_part(), day_part(), camera_part())
    listed = upload_client.get("/api/recordings", params={"day": FRIDAY, "camera": "CAM-001"})
    assert listed.json()[0] == {
        "id": "rec-new1",
        "camera": "CAM-001",
        "day": FRIDAY,
        "startTime": "00:00:00",
        "lengthSeconds": 0,
        "status": "waiting",
    }
    days = upload_client.get("/api/days", params={"camera": "CAM-001"}).json()
    assert days[-1] == {"day": FRIDAY, "recordings": 5, "ready": 2}


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("DOCK.MP4", "video/mp4"), ("dock.mp4", "Video/MP4"), ("dock.mp4", "video/mp4; x=1")],
)
def test_the_mp4_checks_ignore_case_and_parameters(
    upload_client: TestClient, filename: str, content_type: str
) -> None:
    response = upload(
        upload_client,
        video_part(filename=filename, content_type=content_type),
        day_part(),
        camera_part(),
    )
    assert response.status_code == 202


def test_a_video_of_exactly_the_limit_is_accepted(small_limit_client: TestClient) -> None:
    video = FAKE_MP4[:SMALL_LIMIT]
    assert len(video) == SMALL_LIMIT
    response = upload(small_limit_client, video_part(video), day_part(), camera_part())
    assert response.status_code == 202


def test_the_upload_is_never_written_to_disk(upload_client: TestClient, tmp_path: Path) -> None:
    before = files_in(tmp_path)
    assert upload(upload_client, video_part(), day_part(), camera_part()).status_code == 202
    assert files_in(tmp_path) == before


def test_the_documented_limit_is_200_mib() -> None:
    assert MAX_UPLOAD_BYTES == 200 * 1024 * 1024


# --- 413 file_too_large -------------------------------------------------------------------


def test_a_video_over_the_limit_is_413(small_limit_client: TestClient) -> None:
    video = FAKE_MP4 + bytes(SMALL_LIMIT)
    response = upload(small_limit_client, video_part(video), day_part())
    message = assert_error(response, 413, "file_too_large")
    assert message == "The video is larger than the 1024 bytes limit."
    listed = small_limit_client.get("/api/recordings", params={"day": FRIDAY, "camera": "CAM-001"})
    assert "waiting" not in [recording["status"] for recording in listed.json()[:1]]


def test_a_streamed_body_without_a_length_is_cut_off_at_the_limit(
    small_limit_client: TestClient,
) -> None:
    body = multipart(video_part(FAKE_MP4 + bytes(64 * 1024)), day_part())
    chunks = [body[start : start + 4096] for start in range(0, len(body), 4096)]
    response = small_limit_client.post(
        "/api/recordings", content=iter(chunks), headers={"content-type": MULTIPART}
    )
    assert "content-length" not in response.request.headers
    assert_error(response, 413, "file_too_large")


def test_a_declared_length_over_200_mib_is_refused_before_reading(client: TestClient) -> None:
    declared = MAX_UPLOAD_BYTES + FORM_OVERHEAD_BYTES + 1
    response = client.post(
        "/api/recordings",
        content=multipart(video_part(), day_part()),
        headers={"content-type": MULTIPART, "content-length": str(declared)},
    )
    message = assert_error(response, 413, "file_too_large")
    assert message == "The video is larger than the 200 MiB limit."


# --- 415 unsupported_media_type -----------------------------------------------------------


@pytest.mark.parametrize(
    "part",
    [
        video_part(filename="dock.avi"),
        video_part(filename="dock.mp4.exe"),
        video_part(filename="dock"),
        video_part(content_type="video/quicktime"),
        video_part(content_type="application/octet-stream"),
        video_part(data=b"GIF89a" + bytes(64)),
        video_part(data=b"\x00\x00\x00\x18moov" + bytes(64)),
        video_part(data=b"\x00\x00\x00\x18ft"),
        video_part(data=b""),
    ],
    ids=[
        "avi-name",
        "double-extension",
        "no-extension",
        "quicktime-type",
        "octet-stream-type",
        "gif-bytes",
        "no-ftyp-box",
        "too-short",
        "empty",
    ],
)
def test_a_file_that_is_not_an_mp4_is_415(
    client: TestClient, part: tuple[str, str | None, str | None, bytes]
) -> None:
    message = assert_error(upload(client, part, day_part()), 415, "unsupported_media_type")
    assert message == "The upload must be an MP4 video (.mp4)."


@pytest.mark.parametrize(
    "content_type",
    [None, "application/json", "application/x-www-form-urlencoded", "multipart/form-data"],
)
def test_a_body_that_is_not_multipart_is_415(client: TestClient, content_type: str | None) -> None:
    headers = {} if content_type is None else {"content-type": content_type}
    response = client.post("/api/recordings", content=b'{"day": "2026-10-30"}', headers=headers)
    message = assert_error(response, 415, "unsupported_media_type")
    assert message == "Send the video as multipart/form-data with the MP4 in the field named file."


# --- 422 validation_error -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("parts", "message"),
    [
        ((video_part(), camera_part()), "day: is required"),
        (
            (video_part(), day_part("30/10/2026"), camera_part()),
            "day: must be a date written YYYY-MM-DD",
        ),
        (
            (video_part(), day_part("2026-02-30"), camera_part()),
            "day: must be a valid date written YYYY-MM-DD",
        ),
        ((video_part(), day_part(""), camera_part()), "day: must be a date written YYYY-MM-DD"),
        ((video_part(), day_part()), "camera: is required"),
        ((video_part(), day_part(), camera_part(), camera_part()), "camera: send it once"),
        ((video_part(),), "day: is required; camera: is required"),
        ((video_part(), day_part(), day_part()), "day: send it once"),
        ((day_part(),), "file: is required"),
        ((("file", None, None, b"not a file"), day_part()), "file: must be an uploaded file"),
        ((video_part(), video_part(), day_part()), "file: send exactly one file"),
        (
            (("video", "dock.mp4", "video/mp4", FAKE_MP4), day_part()),
            "body: send the video in the field named file",
        ),
        (
            (video_part(), day_part(), camera_part("../etc")),
            "camera: must be 1 to 64 letters, digits, '-' or '_'",
        ),
        ((video_part(), ("day", None, None, b"2" * 2048)), "day: is too long"),
        (
            (video_part(), day_part(), *[("extra", None, None, b"x")] * 7),
            "body: has too many form fields",
        ),
    ],
)
def test_a_bad_form_is_422(
    client: TestClient, parts: tuple[tuple[str, str | None, str | None, bytes], ...], message: str
) -> None:
    assert assert_error(upload(client, *parts), 422, "validation_error") == message


def test_a_form_that_ends_early_is_422(client: TestClient) -> None:
    body = multipart(video_part(), day_part(), close=False)
    response = client.post("/api/recordings", content=body, headers={"content-type": MULTIPART})
    assert assert_error(response, 422, "validation_error") == "body: the form ended early"


def test_an_unknown_camera_is_404(client: TestClient) -> None:
    response = upload(client, video_part(), day_part(), camera_part("CAM-999"))
    assert assert_error(response, 404, "not_found") == "Camera not found."


def test_extra_text_fields_are_ignored(upload_client: TestClient) -> None:
    response = upload(
        upload_client, video_part(), day_part(), camera_part(), ("comment", None, None, b"hi")
    )
    assert response.status_code == 202


def test_the_filename_is_never_echoed(client: TestClient) -> None:
    filename = "secret-plan-C__Users_me.avi"
    response = upload(client, video_part(filename=filename), day_part())
    assert_error(response, 415, "unsupported_media_type")
    assert "secret-plan" not in response.text
