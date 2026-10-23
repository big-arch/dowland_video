"""Интеграционный тест реального пути yt-dlp: локальный HTTP-сервер + ffmpeg."""

from __future__ import annotations

import functools
import http.server
import shutil
import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from mediagrab.config import Settings
from mediagrab.downloader import Downloader, Progress
from mediagrab.errors import FileTooLarge

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="нужен ffmpeg"),
]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: D102 - глушим логи сервера
        pass


def make_settings(tmp_path: Path, **overrides) -> Settings:
    settings = Settings(
        bot_token="",
        download_dir=tmp_path / "dl",
        data_dir=tmp_path / "data",
        cookies_dir=tmp_path / "cookies",
        max_upload_mb=50,
        max_concurrent=1,
        rate_limit_sec=0,
        default_video_height=720,
        default_audio_kbps=192,
        proxy=None,
        local_api_url=None,
        log_level="INFO",
        ffmpeg_path=None,
        js_runtime="none",
        threads_enabled=True,
    )
    return replace(settings, **overrides) if overrides else settings


@pytest.fixture(scope="module")
def media_server(tmp_path_factory) -> str:
    root = tmp_path_factory.mktemp("media")
    sample = root / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15",
            "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", "2", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(sample),
        ],
        check=True,
    )

    handler = functools.partial(_QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_download_video(media_server: str, tmp_path: Path) -> None:
    downloader = Downloader(make_settings(tmp_path))
    events: list[Progress] = []

    result = downloader.fetch(
        url=f"{media_server}/sample.mp4",
        platform="test",
        kind="video",
        quality=720,
        workdir=tmp_path / "video",
        on_progress=events.append,
        cancel=threading.Event(),
    )

    assert result.ext == "mp4"
    assert result.path.is_file()
    assert result.size > 10_000
    assert events, "прогресс не приходил"
    assert any(event.stage == "downloading" for event in events)


def test_extract_mp3(media_server: str, tmp_path: Path) -> None:
    downloader = Downloader(make_settings(tmp_path))

    result = downloader.fetch(
        url=f"{media_server}/sample.mp4",
        platform="test",
        kind="audio",
        quality=128,
        workdir=tmp_path / "audio",
        on_progress=lambda _: None,
        cancel=threading.Event(),
    )

    assert result.ext == "mp3"
    assert result.size > 1_000


def test_file_too_large(media_server: str, tmp_path: Path) -> None:
    downloader = Downloader(make_settings(tmp_path, max_upload_mb=0))

    with pytest.raises(FileTooLarge):
        downloader.fetch(
            url=f"{media_server}/sample.mp4",
            platform="test",
            kind="video",
            quality=720,
            workdir=tmp_path / "limit",
            on_progress=lambda _: None,
            cancel=threading.Event(),
        )
