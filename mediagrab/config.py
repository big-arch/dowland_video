"""Конфигурация приложения: .env + переменные окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .quality import BEST_VIDEO

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_VIDEO_HEIGHT = BEST_VIDEO
DEFAULT_AUDIO_KBPS = 192


def load_dotenv(path: Path) -> None:
    """Минимальный загрузчик .env. Реальные переменные окружения приоритетнее файла."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return max(minimum, value)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on", "да"}


def _env_ids(name: str) -> frozenset[int]:
    raw = os.getenv(name, "")
    result: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            result.add(int(chunk))
    return frozenset(result)


@dataclass(slots=True)
class Settings:
    """Все настройки бота в одном месте."""

    bot_token: str
    download_dir: Path
    data_dir: Path
    cookies_dir: Path
    max_upload_mb: int
    max_concurrent: int
    rate_limit_sec: int
    default_video_height: int
    default_audio_kbps: int
    proxy: str | None
    local_api_url: str | None
    log_level: str
    ffmpeg_path: str | None
    js_runtime: str | None
    threads_enabled: bool
    admin_ids: frozenset[int] = field(default_factory=frozenset)
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    keep_files: bool = False
    request_timeout: int = 30
    drop_pending_updates: bool = True

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        for path in (self.download_dir, self.data_dir, self.cookies_dir):
            path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        local_api = _env_str("TELEGRAM_LOCAL_API_URL") or None
        default_limit = 2000 if local_api else 50

        max_upload_mb = _env_int("MAX_UPLOAD_MB", default_limit, minimum=1)
        max_upload_mb = min(max_upload_mb, default_limit)

        return cls(
            bot_token=_env_str("BOT_TOKEN") or _env_str("TELEGRAM_BOT_TOKEN"),
            download_dir=Path(_env_str("DOWNLOAD_DIR", "downloads")).expanduser(),
            data_dir=Path(_env_str("DATA_DIR", "data")).expanduser(),
            cookies_dir=Path(_env_str("COOKIES_DIR", "cookies")).expanduser(),
            max_upload_mb=max_upload_mb,
            max_concurrent=_env_int("MAX_CONCURRENT_DOWNLOADS", 2, minimum=1),
            rate_limit_sec=_env_int("RATE_LIMIT_SECONDS", 10, minimum=0),
            default_video_height=_env_int("DEFAULT_VIDEO_HEIGHT", DEFAULT_VIDEO_HEIGHT, minimum=0),
            default_audio_kbps=_env_int("DEFAULT_AUDIO_KBPS", DEFAULT_AUDIO_KBPS, minimum=64),
            proxy=_env_str("PROXY_URL") or None,
            local_api_url=local_api,
            log_level=_env_str("LOG_LEVEL", "INFO").upper() or "INFO",
            ffmpeg_path=_env_str("FFMPEG_PATH") or _env_str("FFMPEG_LOCATION") or None,
            js_runtime=_env_str("YTDLP_JS_RUNTIME", "auto") or "auto",
            threads_enabled=_env_bool("THREADS_ENABLED", True),
            admin_ids=_env_ids("ADMIN_IDS"),
            allowed_user_ids=_env_ids("ALLOWED_USER_IDS"),
            keep_files=_env_bool("KEEP_FILES", False),
            request_timeout=_env_int("REQUEST_TIMEOUT", 30, minimum=5),
            drop_pending_updates=_env_bool("DROP_PENDING_UPDATES", True),
        )
