from __future__ import annotations

import pytest

from mediagrab.config import Settings
from mediagrab.errors import DownloadFailed
from mediagrab.threads import ThreadsResolver

PAGE = r"""
<html><head>
<meta property="og:title" content="Alice on Threads" />
<meta property="og:image" content="https://cdn.example/cover.jpg" />
</head><body>
<script type="application/json">{"require":[["PolarisPostRootQuery",null,{"post":{
"video_versions":[
 {"type":101,"url":"https:\/\/cdn.example\/low.mp4?x=1","width":480,"height":854},
 {"type":101,"url":"https:\/\/cdn.example\/high.mp4?x=2","width":720,"height":1280}
],
"video_duration":12.5,
"owner":{"username":"alice"}
}}]]}</script>
</body></html>
"""


def make_resolver(tmp_path) -> ThreadsResolver:
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
    return ThreadsResolver(settings)


def test_parse_prefers_highest_version(tmp_path) -> None:
    media = make_resolver(tmp_path).parse(PAGE)
    assert media.title == "Alice on Threads"
    assert media.duration == 12
    assert media.author == "alice"
    assert media.thumbnail == "https://cdn.example/cover.jpg"
    assert len(media.versions) == 2
    assert media.versions[0].url == "https://cdn.example/high.mp4?x=2"
    assert media.versions[0].height == 1280


def test_parse_og_video_fallback(tmp_path) -> None:
    page = (
        '<html><head><meta property="og:title" content="Clip" />'
        '<meta property="og:video" content="https://cdn.example/only.mp4" />'
        "</head></html>"
    )
    media = make_resolver(tmp_path).parse(page)
    assert [v.url for v in media.versions] == ["https://cdn.example/only.mp4"]


def test_parse_mp4_fallback(tmp_path) -> None:
    page = '<script>var x={"u":"https:\\/\\/cdn.example\\/raw.mp4?a=1"}</script>'
    media = make_resolver(tmp_path).parse(page)
    assert media.versions[0].url.startswith("https://cdn.example/raw.mp4")


def test_parse_without_video_raises(tmp_path) -> None:
    with pytest.raises(DownloadFailed):
        make_resolver(tmp_path).parse("<html><body>просто текст</body></html>")


def test_cookie_header_from_netscape_file(tmp_path) -> None:
    resolver = make_resolver(tmp_path)
    resolver.settings.cookies_dir.mkdir(parents=True)
    (resolver.settings.cookies_dir / "threads.txt").write_text(
        "# Netscape HTTP Cookie File\n"
        ".threads.com\tTRUE\t/\tTRUE\t0\tsessionid\tabc\n"
        "#HttpOnly_.threads.com\tTRUE\t/\tTRUE\t0\tcsrftoken\txyz\n"
        ".instagram.com\tTRUE\t/\tTRUE\t0\tds_user_id\t42\n"
        ".example.com\tTRUE\t/\tTRUE\t0\tnope\t1\n",
        encoding="utf-8",
    )
    header = resolver._cookie_header()
    assert "sessionid=abc" in header
    assert "csrftoken=xyz" in header
    assert "ds_user_id=42" in header
    assert "nope=1" not in header
