"""Разбор ссылок: нормализация, определение площадки, короткие ссылки."""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

log = logging.getLogger(__name__)

# площадка -> домены (совпадение по хосту или поддомену)
PLATFORM_HOSTS: dict[str, tuple[str, ...]] = {
    "youtube": ("youtube.com", "youtu.be", "youtube-nocookie.com"),
    "instagram": ("instagram.com", "instagr.am", "ddinstagram.com"),
    "tiktok": ("tiktok.com",),
    "threads": ("threads.com", "threads.net"),
    "x": ("x.com", "twitter.com", "t.co"),
    "rutube": ("rutube.ru",),
    "vk": ("vk.com", "vk.ru", "vkvideo.ru"),
}

# какие query-параметры имеет смысл сохранять
_KEEP_QUERY: dict[str, set[str]] = {
    "youtube": {"v", "t", "start"},
    "rutube": {"p"},
    "vk": {"oid", "id", "z", "t", "hd"},
}

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'«»]+", re.IGNORECASE)
_BARE_RE = re.compile(
    r"(?<![\w./@-])("
    r"(?:youtube\.com|youtu\.be|instagram\.com|tiktok\.com|threads\.(?:com|net)|"
    r"x\.com|twitter\.com|rutube\.ru|vk\.com|vkvideo\.ru|vk\.ru)"
    r"/[^\s<>\"'«»]+)",
    re.IGNORECASE,
)
_TRAILING = ".,;:!?)]}>»\"'"

_SHORTENERS = ("t.co", "vm.tiktok.com", "vt.tiktok.com", "instagram.com/share/")


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def detect_platform(url: str) -> str | None:
    """Возвращает ключ площадки или None."""
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if not host:
        return None
    for platform, domains in PLATFORM_HOSTS.items():
        if any(_host_matches(host, domain) for domain in domains):
            return platform
    return None


def normalize_url(raw: str) -> str | None:
    """Чистит ссылку: схема, www, tracking-параметры, хвостовая пунктуация."""
    raw = (raw or "").strip().strip("<>\"'")
    if not raw:
        return None
    if raw.startswith("//"):
        raw = "https:" + raw
    elif "://" not in raw:
        raw = "https://" + raw.lstrip("/")

    try:
        parts = urlsplit(raw)
    except ValueError:
        return None

    host = (parts.hostname or "").lower().rstrip(".")
    if not host or "." not in host:
        return None
    if host.startswith("www."):
        host = host[4:]

    platform = detect_platform(f"https://{host}/")
    keep = _KEEP_QUERY.get(platform or "", set())
    if platform == "youtube" and parts.path.rstrip("/") == "/playlist":
        keep = keep | {"list"}

    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key in keep
    ]
    # VK: video_ext.php требует oid/id в query, иначе ссылка нерабочая
    if platform == "vk" and "video_ext.php" in parts.path and not query_pairs:
        query_pairs = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key in {"oid", "id", "hash", "hd"}
        ]

    netloc = host
    # TikTokIE распознаёт полные ссылки на ролик только на www.tiktok.com.
    # Короткие vm/vt ссылки оставляем для соответствующего extractor.
    if platform == "tiktok" and host == "tiktok.com":
        netloc = "www.tiktok.com"
    if parts.port and parts.port not in (80, 443):
        netloc = f"{host}:{parts.port}"

    path = parts.path or "/"
    # yt-dlp ожидает основной домен Rutube, включая мобильные ссылки.
    if platform == "rutube":
        netloc = "rutube.ru"
        if path.startswith("/shorts/"):
            path = "/video/" + path[len("/shorts/"):]
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    return urlunsplit(("https", netloc, path, urlencode(query_pairs), ""))


def extract_urls(text: str) -> list[str]:
    """Достаёт из текста все ссылки, нормализует и отбрасывает мусор."""
    if not text:
        return []
    candidates: list[str] = [m.group(0) for m in _URL_RE.finditer(text)]
    candidates += [m.group(1) for m in _BARE_RE.finditer(text)]

    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.rstrip(_TRAILING)
        normalized = normalize_url(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def is_playlist_url(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    query = dict(parse_qsl(parts.query))
    if _host_matches(host, "youtube.com") and "list" in query and "v" not in query:
        return True
    if _host_matches(host, "rutube.ru") and "/playlist/" in parts.path:
        return True
    return False


def resolve_short_url(url: str, *, proxy: str | None = None, timeout: int = 8) -> str:
    """Раскрывает t.co / vm.tiktok.com и подобные редиректы (best effort)."""
    lowered = url.lower()
    if not any(marker in lowered for marker in _SHORTENERS):
        return url

    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)

    for method in ("HEAD", "GET"):
        request = urllib.request.Request(
            url,
            method=method,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
                **({"Range": "bytes=0-0"} if method == "GET" else {}),
            },
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                final = response.geturl()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.debug("short url resolve failed (%s): %s", method, exc)
            continue
        if final and final != url:
            normalized = normalize_url(final)
            if normalized:
                return normalized
    return url


def split_supported(text: str) -> tuple[list[str], list[str]]:
    """Возвращает (поддерживаемые, неподдерживаемые) ссылки из текста."""
    supported: list[str] = []
    unsupported: list[str] = []
    for url in extract_urls(text):
        (supported if detect_platform(url) else unsupported).append(url)
    return supported, unsupported
