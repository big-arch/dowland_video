"""Загрузка видео из Threads (yt-dlp пока не умеет threads.com из коробки).

Страница поста содержит JSON с массивом ``video_versions`` и/или
``og:video``. Забираем самый качественный mp4 и качаем его напрямую
с CDN, подставляя необходимые заголовки.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Settings
from .errors import DownloadCancelled, DownloadFailed, FileTooLarge

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Mode": "navigate",
}

_VIDEO_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "video/*,*/*;q=0.8",
    "Referer": "https://www.threads.com/",
    "Origin": "https://www.threads.com",
}

_MP4_RE = re.compile(r"https?:(?:\\?/){2}[^\"'\s]+", re.IGNORECASE)
_DURATION_RE = re.compile(r'"video_duration"\s*:\s*([\d.]+)')
_OWNER_RE = re.compile(r'"owner"\s*:\s*\{[^{}]*?"username"\s*:\s*"([^"]+)"')


@dataclass(slots=True)
class VideoVersion:
    url: str
    width: int = 0
    height: int = 0
    bitrate: int = 0

    @property
    def rank(self) -> tuple[int, int, int]:
        return (self.height, self.width, self.bitrate)


@dataclass(slots=True)
class ThreadsMedia:
    title: str
    versions: list[VideoVersion] = field(default_factory=list)
    duration: int | None = None
    thumbnail: str | None = None
    author: str = ""


def _unescape_url(value: str) -> str:
    value = html_lib.unescape(value)
    if "\\/" in value or "\\u" in value:
        try:
            return json.loads(f'"{value}"')
        except json.JSONDecodeError:
            value = value.replace("\\/", "/")
    return value


def _json_array_after(html: str, key: str) -> list[dict] | None:
    marker = f'"{key}"'
    search_from = 0
    decoder = json.JSONDecoder()
    while True:
        index = html.find(marker, search_from)
        if index < 0:
            return None
        start = html.find("[", index)
        if start < 0:
            return None
        try:
            value, _ = decoder.raw_decode(html, start)
        except ValueError:
            search_from = index + len(marker)
            continue
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        search_from = index + len(marker)


def _meta(html: str, prop: str) -> str | None:
    pattern = re.compile(
        r"<meta[^>]*?(?:property|name)=[\"']" + re.escape(prop) + r"[\"'][^>]*>",
        re.IGNORECASE,
    )
    match = pattern.search(html)
    if not match:
        return None
    content = re.search(r'content=["\']([^"\']*)["\']', match.group(0), re.IGNORECASE)
    return html_lib.unescape(content.group(1)) if content else None


class ThreadsResolver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ------------------------------------------------------------------ fetch

    def _opener(self) -> urllib.request.OpenerDirector:
        handlers: list[urllib.request.BaseHandler] = []
        if self.settings.proxy:
            handlers.append(
                urllib.request.ProxyHandler(
                    {"http": self.settings.proxy, "https": self.settings.proxy}
                )
            )
        return urllib.request.build_opener(*handlers)

    def _cookie_header(self) -> str:
        """Достаёт cookies Threads/Instagram из Netscape-файла, если он есть."""
        path = self.settings.cookies_dir / "threads.txt"
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

        pairs: list[str] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_") :]
            elif line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 7:
                continue
            domain, _flag, _path, _secure, _expires, name, value = fields[:7]
            if "threads" in domain or "instagram" in domain:
                pairs.append(f"{name}={value}")
        return "; ".join(pairs)

    def _headers(self, base: dict[str, str]) -> dict[str, str]:
        headers = dict(base)
        if cookie := self._cookie_header():
            headers["Cookie"] = cookie
        return headers

    def _get_page(self, url: str) -> str:
        request = urllib.request.Request(url, headers=self._headers(_BASE_HEADERS))
        try:
            with self._opener().open(request, timeout=self.settings.request_timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            raise DownloadFailed(
                f"Threads ответил ошибкой {exc.code}. Попробуйте позже или другую ссылку.",
                technical=f"threads http {exc.code}",
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DownloadFailed(
                "Не удалось открыть пост в Threads. Проверьте ссылку и доступ к сети.",
                technical=f"threads network: {exc}",
            ) from exc

    # ---------------------------------------------------------------- parsing

    def parse(self, page: str) -> ThreadsMedia:
        title = _meta(page, "og:title") or _meta(page, "twitter:title") or "Threads video"
        title = re.sub(r"\s*[|·]\s*Threads\s*$", "", title).strip() or "Threads video"

        versions: dict[str, VideoVersion] = {}
        for item in _json_array_after(page, "video_versions") or []:
            url = item.get("url")
            if not isinstance(url, str) or not url.startswith("http"):
                continue
            versions[url] = VideoVersion(
                url=url,
                width=int(item.get("width") or 0),
                height=int(item.get("height") or 0),
                bitrate=int(item.get("bitrate") or 0),
            )

        if not versions:
            og_video = _meta(page, "og:video") or _meta(page, "og:video:secure_url")
            if og_video and og_video.startswith("http") and ".mp4" in og_video:
                versions[og_video] = VideoVersion(url=og_video)

        if not versions:
            for match in _MP4_RE.finditer(page):
                url = _unescape_url(match.group(0))
                if url.startswith("http") and ".mp4" in url.lower():
                    versions[url] = VideoVersion(url=url)

        if not versions:
            raise DownloadFailed(
                "В этом посте Threads не нашлось видео. Возможно, это текст, фото "
                "или пост с ограниченным доступом.",
                technical="threads: no video_versions/og:video",
            )

        duration = None
        duration_match = _DURATION_RE.search(page)
        if duration_match:
            try:
                duration = int(float(duration_match.group(1)))
            except ValueError:
                duration = None

        owner_match = _OWNER_RE.search(page)
        return ThreadsMedia(
            title=title,
            versions=sorted(versions.values(), key=lambda v: v.rank, reverse=True),
            duration=duration,
            thumbnail=_meta(page, "og:image"),
            author=owner_match.group(1) if owner_match else "",
        )

    def resolve(self, url: str) -> ThreadsMedia:
        return self.parse(self._get_page(url))

    # --------------------------------------------------------------- download

    def download(
        self,
        media: ThreadsMedia,
        destination: Path,
        *,
        max_bytes: int,
        cancel,
        on_progress: Callable[[int, int], None],
        max_height: int = 0,
        allow_quality_fallback: bool = True,
    ) -> tuple[Path, VideoVersion]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None

        versions = [v for v in media.versions if not max_height or not v.height or v.height <= max_height]
        if not versions:
            raise DownloadFailed("У видео нет версии в выбранном разрешении. Выберите качество выше.")
        for index, version in enumerate(versions):
            target = destination.with_name(f"{destination.stem}_{index}.mp4")
            try:
                self._download_one(
                    version.url,
                    target,
                    max_bytes=max_bytes,
                    cancel=cancel,
                    on_progress=on_progress,
                )
                return target, version
            except FileTooLarge as exc:
                last_error = exc
                target.unlink(missing_ok=True)
                if not allow_quality_fallback:
                    raise
                continue

        if isinstance(last_error, FileTooLarge):
            raise last_error
        raise DownloadFailed("Не удалось скачать видео из Threads.")

    def _download_one(
        self,
        url: str,
        target: Path,
        *,
        max_bytes: int,
        cancel,
        on_progress: Callable[[int, int], None],
    ) -> None:
        request = urllib.request.Request(url, headers=self._headers(_VIDEO_HEADERS))
        try:
            response = self._opener().open(request, timeout=self.settings.request_timeout)
        except urllib.error.HTTPError as exc:
            raise DownloadFailed(
                f"CDN Threads не отдал видео (HTTP {exc.code}).",
                technical=f"threads cdn {exc.code}",
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DownloadFailed(
                "Не удалось скачать видео из Threads.",
                technical=f"threads cdn: {exc}",
            ) from exc

        with response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "text/html" in content_type:
                raise DownloadFailed(
                    "Threads вернул страницу вместо видео — возможно, нужен вход или cookies.",
                    technical=f"threads cdn content-type={content_type}",
                )

            total = int(response.headers.get("Content-Length") or 0)
            if total and total > max_bytes:
                raise FileTooLarge(total, max_bytes)

            downloaded = 0
            with target.open("wb") as file:
                while True:
                    if cancel.is_set():
                        raise DownloadCancelled()
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    file.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise FileTooLarge(downloaded, max_bytes)
                    on_progress(downloaded, total)

        if target.stat().st_size < 1024:
            target.unlink(missing_ok=True)
            raise DownloadFailed("Threads вернул пустой файл.")
