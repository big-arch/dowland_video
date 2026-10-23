from __future__ import annotations

import threading

import pytest

from mediagrab.config import Settings
from mediagrab.downloader import Downloader, _friendly_error
from mediagrab.errors import FileTooLarge


def make_settings(tmp_path) -> Settings:
    return Settings(
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


def test_video_ladder_descends() -> None:
    assert Downloader._ladder("video", 720) == [720, 480, 360, 240, 144]
    assert Downloader._ladder("video", 1080)[0] == 1080
    assert Downloader._ladder("video", 100)[-1] == 144


def test_audio_ladder_descends() -> None:
    assert Downloader._ladder("audio", 192) == [192, 128, 96, 64]
    assert Downloader._ladder("audio", 320)[0] == 320


def test_video_format_limits_height(tmp_path) -> None:
    downloader = Downloader(make_settings(tmp_path))
    selector = downloader._video_format(720)
    assert "height<=720" in selector
    assert "avc1" in selector


def test_audio_options_use_requested_bitrate(tmp_path) -> None:
    downloader = Downloader(make_settings(tmp_path))
    options = downloader._base_options(
        platform="youtube",
        kind="audio",
        value=128,
        workdir=tmp_path / "dl",
        on_progress=lambda _: None,
        cancel=threading.Event(),
    )
    audio_pp = [pp for pp in options["postprocessors"] if pp["key"] == "FFmpegExtractAudio"]
    assert audio_pp and audio_pp[0]["preferredquality"] == "128"
    assert options["format"].startswith("bestaudio/")


def test_estimate_size_sums_formats() -> None:
    info = {
        "requested_formats": [
            {"filesize": 10},
            {"filesize_approx": 5},
        ]
    }
    assert Downloader._estimate_size(info) == 15
    assert Downloader._estimate_size({"requested_formats": [{"filesize": 10}, {}]}) == 0
    assert Downloader._estimate_size({"filesize": 7}) == 7


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("Sign in to confirm you're not a bot", "cookies"),
        ("ERROR: Login required", "cookies"),
        ("This video is private", "приватный"),
        ("Unsupported URL: https://x", "не распознана"),
        ("HTTP Error 429: Too Many Requests", "cookies"),
        ("No video formats found", "формат"),
    ],
)
def test_friendly_error_mapping(text: str, needle: str) -> None:
    assert needle.lower() in _friendly_error(text, "youtube").lower()


def test_file_too_large_marker() -> None:
    exc = FileTooLarge(100 * 1024 * 1024, 50 * 1024 * 1024)
    assert str(exc) == "DL_TOO_LARGE:104857600:52428800"
    assert "лимит" in exc.user_message


def test_stream_without_content_length_stops_at_limit(tmp_path) -> None:
    downloader = Downloader(make_settings(tmp_path))
    options = downloader._base_options(
        platform="rutube", kind="video", value=720,
        workdir=tmp_path / "dl", on_progress=lambda _: None,
        cancel=threading.Event(),
    )
    with pytest.raises(FileTooLarge):
        options["progress_hooks"][0]({
            "status": "downloading", "downloaded_bytes": 51 * 1024 * 1024,
        })


@pytest.mark.parametrize("platform", ["rutube", "tiktok"])
def test_platform_error_includes_actionable_advice(platform):
    message = _friendly_error("Unexpected response", platform)
    assert platform.lower() in message.lower()
    assert "PROXY_URL" in message
