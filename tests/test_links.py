from __future__ import annotations

from pathlib import Path

import pytest

from mediagrab.config import Settings
from mediagrab.links import (
    detect_platform,
    extract_urls,
    is_playlist_url,
    normalize_url,
    split_supported,
)


def test_normalize_strips_youtube_tracking_and_playlist() -> None:
    url = normalize_url(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&index=2&si=track"
    )
    assert url == "https://youtube.com/watch?v=dQw4w9WgXcQ"


def test_normalize_short_youtube() -> None:
    assert normalize_url("youtu.be/abcDEF123?t=42") == "https://youtu.be/abcDEF123?t=42"


def test_normalize_instagram_reel() -> None:
    url = normalize_url("https://www.instagram.com/reel/C1abc/?igsh=xyz&utm_source=ig")
    assert url == "https://instagram.com/reel/C1abc"


def test_normalize_tiktok_short() -> None:
    assert normalize_url("https://vm.tiktok.com/ZMabc/") == "https://vm.tiktok.com/ZMabc"


def test_normalize_strips_www_and_keeps_path() -> None:
    assert (
        normalize_url("https://www.rutube.ru/video/12345/") == "https://rutube.ru/video/12345"
    )


def test_normalize_vk_video_ext_keeps_ids() -> None:
    url = normalize_url("https://vk.com/video_ext.php?oid=-123&id=456&hash=abc&hd=2")
    assert "oid=-123" in url
    assert "id=456" in url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://youtube.com/watch?v=1", "youtube"),
        ("https://music.youtube.com/watch?v=1", "youtube"),
        ("https://youtu.be/1", "youtube"),
        ("https://www.instagram.com/reel/1/", "instagram"),
        ("https://vm.tiktok.com/ZM1/", "tiktok"),
        ("https://www.threads.com/@a/post/1", "threads"),
        ("https://threads.net/@a/post/1", "threads"),
        ("https://x.com/a/status/1", "x"),
        ("https://twitter.com/a/status/1", "x"),
        ("https://rutube.ru/video/1/", "rutube"),
        ("https://vk.com/video-1_2", "vk"),
        ("https://vkvideo.ru/video-1_2", "vk"),
        ("https://example.com/video", None),
        ("https://notyoutube.com/watch?v=1", None),
    ],
)
def test_detect_platform(url: str, expected: str | None) -> None:
    assert detect_platform(url) == expected


def test_extract_urls_from_text_with_punctuation() -> None:
    text = "Смотри: https://youtu.be/abc?t=10, и ещё (https://www.tiktok.com/@u/video/1)."
    urls = extract_urls(text)
    assert urls[0] == "https://youtu.be/abc?t=10"
    assert urls[1] == "https://tiktok.com/@u/video/1"


def test_extract_bare_domain() -> None:
    assert extract_urls("rutube.ru/video/abc/")[0] == "https://rutube.ru/video/abc"


def test_extract_rejects_garbage() -> None:
    assert extract_urls("просто текст без ссылок") == []
    assert extract_urls("https://") == []


def test_playlist_detection() -> None:
    assert is_playlist_url("https://youtube.com/playlist?list=PL1")
    assert not is_playlist_url("https://youtube.com/watch?v=1&list=PL1")
    assert is_playlist_url("https://rutube.ru/playlist/123/")


def test_normalize_keeps_playlist_id() -> None:
    url = normalize_url("https://www.youtube.com/playlist?list=PL1&si=track")
    assert url == "https://youtube.com/playlist?list=PL1"
    assert is_playlist_url(url)


def test_split_supported() -> None:
    supported, unsupported = split_supported(
        "https://youtu.be/1 https://example.com/x https://vk.com/video-1_2"
    )
    assert supported == ["https://youtu.be/1", "https://vk.com/video-1_2"]
    assert unsupported == ["https://example.com/x"]


def test_settings_limit_depends_on_local_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)
    monkeypatch.delenv("TELEGRAM_LOCAL_API_URL", raising=False)
    assert Settings.from_env().max_upload_mb == 50

    monkeypatch.setenv("TELEGRAM_LOCAL_API_URL", "http://127.0.0.1:8081")
    assert Settings.from_env().max_upload_mb == 2000


def test_drop_pending_updates_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DROP_PENDING_UPDATES", "false")
    assert Settings.from_env().drop_pending_updates is False

    monkeypatch.setenv("DROP_PENDING_UPDATES", "true")
    assert Settings.from_env().drop_pending_updates is True
