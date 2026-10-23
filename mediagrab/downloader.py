"""Скачивание через yt-dlp: форматы, прогресс, отмена, лимиты размера."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yt_dlp
from yt_dlp.utils import DownloadError as YtDlpError

from . import threads as threads_module
from .config import Settings
from .errors import (
    DownloadCancelled,
    DownloadFailed,
    FileTooLarge,
)
from .utils import human_size

log = logging.getLogger(__name__)

VIDEO_HEIGHTS = (2160, 1440, 1080, 720, 480, 360, 240, 144)
AUDIO_BITRATES = (320, 256, 192, 128, 96, 64)

ProgressCallback = Callable[["Progress"], None]

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


@dataclass(slots=True)
class Progress:
    stage: str
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0
    eta: int | None = None
    title: str = ""


@dataclass(slots=True)
class MediaResult:
    path: Path
    kind: str
    platform: str
    title: str
    source_url: str
    size: int
    uploader: str = ""
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    thumbnail: Path | None = None

    @property
    def ext(self) -> str:
        return self.path.suffix.lower().lstrip(".")


def _find_cause(exc: BaseException, types: tuple[type, ...]) -> BaseException | None:
    current: BaseException | None = exc
    for _ in range(12):
        if current is None:
            return None
        if isinstance(current, types):
            return current
        current = current.__cause__ or current.__context__
    return None


def _friendly_error(text: str, platform: str) -> str:
    lowered = text.lower()

    if "dl_cancelled" in lowered:
        return "Загрузка отменена."
    if match := re.search(r"dl_too_large:(\d+):(\d+)", text):
        return FileTooLarge(int(match.group(1)), int(match.group(2))).user_message

    rules: list[tuple[str, str]] = [
        (
            r"sign in to confirm|confirm you.?re not a bot|not a bot",
            "YouTube отклонил запрос с IP сервера. Администратору: обновите cookies "
            "(YOUTUBE_COOKIES_B64 или cookies/youtube.txt). Если ошибка остаётся, "
            "настройте PROXY_URL или перенесите бота с GitHub Actions на другой сервер.",
        ),
        (
            r"login required|login_required|checkpoint|rate.?limit|"
            r"empty media response|requested content is not available|"
            r"please wait a few minutes|too many requests",
            f"{platform.title() if platform else 'Площадка'} требует вход или "
            "ограничил запросы. Положите cookies в папку cookies/ (см. README).",
        ),
        (
            r"private|is not available|not available in your country|geo.?restrict|"
            r"blocked in your country",
            "Контент приватный, удалён или недоступен в регионе сервера.",
        ),
        (
            r"age.?restrict|inappropriate for some users|adult",
            "У контента возрастное ограничение. Нужны cookies от аккаунта 18+.",
        ),
        (
            r"unsupported url",
            "Ссылка не распознана как медиа. Пришлите прямую ссылку на видео или пост.",
        ),
        (
            r"video unavailable|this video is unavailable|has been removed|"
            r"does not exist|404",
            "Видео недоступно: удалено, скрыто или ссылка неверная.",
        ),
        (
            r"no video formats|requested format is not available|only images",
            "Не удалось подобрать формат. Возможно, в посте только фото.",
        ),
        (
            r"timed out|timeout|connection|temporary failure|network",
            "Сеть или площадка не ответили. Попробуйте ещё раз через минуту.",
        ),
        (
            r"ffmpeg|postprocessing",
            "Ошибка обработки файла. Проверьте, что ffmpeg установлен и доступен.",
        ),
        (
            r"live event|is live|live stream",
            "Прямые трансляции не скачиваю — дождитесь окончания эфира.",
        ),
    ]
    for pattern, message in rules:
        if re.search(pattern, lowered):
            return message
    if platform == "tiktok":
        return (
            "TikTok не отдал видео. Откройте ссылку в браузере и проверьте доступность. "
            "Администратору: обновите yt-dlp с curl-cffi, добавьте TIKTOK_COOKIES_B64 "
            "или cookies/tiktok.txt; при блокировке IP настройте PROXY_URL."
        )
    if platform == "rutube":
        return (
            "Rutube не отдал видео. Проверьте доступность ролика из региона сервера "
            "и сохраните параметр ?p= в ссылке с доступом по ссылке. "
            "Администратору: при блокировке IP настройте PROXY_URL; "
            "для роликов с входом добавьте cookies/rutube.txt."
        )
    return "Не удалось скачать медиа. Ссылка может быть недоступна или площадка изменила правила."


class Downloader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ffmpeg = self._locate_ffmpeg(settings.ffmpeg_path)
        self.js_runtime = self._detect_js_runtime()
        self._threads = threads_module.ThreadsResolver(settings)

    # ------------------------------------------------------------- окружение

    @staticmethod
    def _locate_ffmpeg(configured: str | None) -> str | None:
        if configured:
            path = Path(configured).expanduser()
            if path.is_file():
                return str(path)
            if path.is_dir():
                for name in ("ffmpeg.exe", "ffmpeg"):
                    candidate = path / name
                    if candidate.exists():
                        return str(candidate)
            if found := shutil.which(configured):
                return found
        return shutil.which("ffmpeg")

    def _detect_js_runtime(self) -> dict[str, dict] | None:
        preferred = (self.settings.js_runtime or "auto").lower()
        if preferred not in {"auto", "", "none"}:
            return {preferred: {}}
        if preferred == "none":
            return {}
        for runtime in ("node", "deno", "bun"):
            if shutil.which(runtime):
                return {runtime: {}}
        log.warning(
            "Не найден JS runtime (node/deno): YouTube может отдавать не все форматы."
        )
        return None

    def _cookiefile(self, platform: str) -> str | None:
        for name in (f"{platform}.txt", "cookies.txt"):
            path = self.settings.cookies_dir / name
            if path.is_file() and path.stat().st_size > 0:
                return str(path)
        return None

    # ------------------------------------------------------------------ API

    def fetch(
        self,
        *,
        url: str,
        platform: str,
        kind: str,
        quality: int,
        workdir: Path,
        on_progress: ProgressCallback,
        cancel: threading.Event,
    ) -> MediaResult:
        """Скачивает медиа, перебирая качества вниз, если файл слишком большой."""
        workdir = workdir.resolve()
        workdir.mkdir(parents=True, exist_ok=True)

        if kind == "audio" and not self.ffmpeg:
            raise DownloadFailed(
                "Для MP3 нужен ffmpeg. Установите его и перезапустите бота (см. README)."
            )

        if platform == "threads" and self.settings.threads_enabled:
            try:
                return self._fetch_threads(
                    url=url,
                    kind=kind,
                    quality=quality,
                    workdir=workdir / "threads",
                    on_progress=on_progress,
                    cancel=cancel,
                )
            except DownloadCancelled:
                raise
            except DownloadFailed as exc:
                log.warning("Threads resolver не сработал: %s", exc)
                if not self._looks_like_network_error(exc):
                    raise
                # падаем в общий yt-dlp-путь ниже

        ladder = self._ladder(kind, quality)
        last_error: DownloadFailed | None = None

        for index, value in enumerate(ladder):
            if cancel.is_set():
                raise DownloadCancelled()
            attempt_dir = workdir / f"try{index}"
            try:
                return self._fetch_ytdlp(
                    url=url,
                    platform=platform,
                    kind=kind,
                    value=value,
                    workdir=attempt_dir,
                    on_progress=on_progress,
                    cancel=cancel,
                    force_generic=(platform == "threads"),
                )
            except FileTooLarge as exc:
                last_error = exc
                log.info("Файл больше лимита (%s), пробую ниже", human_size(exc.size))
                shutil.rmtree(attempt_dir, ignore_errors=True)
                continue

        raise last_error or DownloadFailed("Не удалось скачать медиа.")

    @staticmethod
    def _looks_like_network_error(exc: DownloadFailed) -> bool:
        text = (exc.technical or "").lower()
        return "threads http" in text or "threads network" in text or "cdn" in text

    @staticmethod
    def _ladder(kind: str, quality: int) -> list[int]:
        values = VIDEO_HEIGHTS if kind == "video" else AUDIO_BITRATES
        index = next((i for i, value in enumerate(values) if value <= quality), len(values) - 1)
        return list(values[index:])

    # ------------------------------------------------------------- yt-dlp

    def _video_format(self, height: int) -> str:
        if self.ffmpeg:
            return (
                f"bv*[height<={height}][ext=mp4][vcodec^=avc1]+ba[ext=m4a]/"
                f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
                f"bv*[height<={height}]+ba/"
                f"b[height<={height}][ext=mp4]/b[height<={height}]/b"
            )
        return f"b[height<={height}][ext=mp4]/b[height<={height}]/b"

    def _base_options(
        self,
        *,
        platform: str,
        kind: str,
        value: int,
        workdir: Path,
        on_progress: ProgressCallback,
        cancel: threading.Event,
    ) -> dict:
        max_bytes = self.settings.max_upload_bytes
        # Для MP3 исходный поток может быть больше лимита: после перекодирования
        # файл станет меньше. Ограничиваем только совсем большие исходники.
        source_limit = (
            max_bytes
            if kind == "video"
            else max(max_bytes * 8, 768 * 1024 * 1024)
        )
        workdir = workdir.resolve()
        workdir.mkdir(parents=True, exist_ok=True)

        def hook(status: dict) -> None:
            if cancel.is_set():
                raise DownloadCancelled()
            info = status.get("info_dict") or {}
            if status.get("status") == "downloading":
                total = int(status.get("total_bytes") or status.get("total_bytes_estimate") or 0)
                downloaded = int(status.get("downloaded_bytes") or 0)
                estimate = self._estimate_size(info)
                if estimate and estimate > source_limit:
                    raise FileTooLarge(estimate, max_bytes)
                if max(total, downloaded) > source_limit:
                    raise FileTooLarge(max(total, downloaded), max_bytes)
                on_progress(
                    Progress(
                        stage="downloading",
                        downloaded=downloaded,
                        total=total,
                        speed=float(status.get("speed") or 0),
                        eta=status.get("eta"),
                        title=str(info.get("title") or ""),
                    )
                )
            elif status.get("status") == "finished":
                on_progress(
                    Progress(
                        stage="processing",
                        downloaded=int(status.get("downloaded_bytes") or 0),
                        total=int(status.get("total_bytes") or 0),
                        title=str(info.get("title") or ""),
                    )
                )

        def pp_hook(status: dict) -> None:
            if cancel.is_set():
                raise DownloadCancelled()
            on_progress(Progress(stage="processing", title=str((status.get("info_dict") or {}).get("title") or "")))

        options: dict = {
            "format": (
                self._video_format(value)
                if kind == "video"
                else "bestaudio/worst[acodec!=none]/b[height<=360]/b"
            ),
            "outtmpl": {"default": "%(title).70B [%(id)s].%(ext)s"},
            "paths": {"home": str(workdir), "temp": str(workdir)},
            "noplaylist": True,
            "playlist_items": "1",
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "no_color": True,
            "nocheckcertificate": False,
            "cachedir": False,
            "trim_file_name": 70,
            "windowsfilenames": True,
            "overwrites": True,
            "continuedl": False,
            "retries": 3,
            "fragment_retries": 3,
            "extractor_retries": 2,
            "file_access_retries": 3,
            "socket_timeout": self.settings.request_timeout,
            "concurrent_fragment_downloads": 4,
            "progress_hooks": [hook],
            "postprocessor_hooks": [pp_hook],
            "ignoreerrors": False,
            "geo_bypass": True,
            "writethumbnail": bool(self.ffmpeg),
            "postprocessors": [],
        }

        if self.ffmpeg:
            options["ffmpeg_location"] = self.ffmpeg
            options["postprocessors"].append(
                {"key": "FFmpegThumbnailsConvertor", "format": "jpg"}
            )
        if self.js_runtime:
            options["js_runtimes"] = self.js_runtime

        if cookie := self._cookiefile(platform):
            options["cookiefile"] = cookie
        if self.settings.proxy:
            options["proxy"] = self.settings.proxy

        if kind == "video":
            options["merge_output_format"] = "mp4"
        else:
            options["prefer_ffmpeg"] = True
            options["keepvideo"] = True
            options["postprocessors"].append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": str(value),
                }
            )
            options["postprocessors"].append({"key": "FFmpegMetadata", "add_metadata": True})

        return options

    @staticmethod
    def _estimate_size(info: dict) -> int:
        formats = info.get("requested_formats") or []
        if not formats:
            return int(info.get("filesize") or info.get("filesize_approx") or 0)
        total = 0
        for fmt in formats:
            size = int(fmt.get("filesize") or fmt.get("filesize_approx") or 0)
            if not size:
                return 0
            total += size
        return total

    def _fetch_ytdlp(
        self,
        *,
        url: str,
        platform: str,
        kind: str,
        value: int,
        workdir: Path,
        on_progress: ProgressCallback,
        cancel: threading.Event,
        force_generic: bool = False,
    ) -> MediaResult:
        options = self._base_options(
            platform=platform,
            kind=kind,
            value=value,
            workdir=workdir,
            on_progress=on_progress,
            cancel=cancel,
        )
        if force_generic:
            options["force_generic_extractor"] = True
        if platform == "threads":
            options.setdefault("http_headers", {})["Referer"] = "https://www.threads.com/"
        elif platform == "rutube":
            options.setdefault("http_headers", {})["Referer"] = "https://rutube.ru/"

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    raise DownloadFailed("Площадка не вернула информацию о видео.")
                if "entries" in info:
                    entries = [entry for entry in (info.get("entries") or []) if entry]
                    if not entries:
                        raise DownloadFailed("Плейлист пуст или недоступен.")
                    info = entries[0]
                path = self._locate_download(ydl, info, workdir, kind)
        except (DownloadCancelled, FileTooLarge, DownloadFailed):
            raise
        except Exception as exc:
            raise self._translate(exc, platform) from exc

        max_bytes = self.settings.max_upload_bytes
        size = path.stat().st_size
        if size > max_bytes and kind == "audio":
            fitted = self._fit_audio_size(workdir, path, value)
            if fitted is not None:
                path = fitted
                size = path.stat().st_size
        if size > max_bytes:
            raise FileTooLarge(size, max_bytes)

        if kind == "video" and path.suffix.lower() not in {".mp4", ".m4v"}:
            path = self._remux_mp4(path)

        thumbnail = self._prepare_thumbnail(workdir, path)
        duration = info.get("duration")
        return MediaResult(
            path=path,
            kind=kind,
            platform=platform,
            title=str(info.get("title") or path.stem),
            source_url=str(info.get("webpage_url") or url),
            size=path.stat().st_size,
            uploader=str(info.get("uploader") or info.get("channel") or ""),
            duration=int(duration) if duration else None,
            width=info.get("width"),
            height=info.get("height"),
            thumbnail=thumbnail,
        )

    @staticmethod
    def _locate_download(ydl, info: dict, workdir: Path, kind: str) -> Path:
        if kind == "audio":
            mp3_files = sorted(
                (p for p in workdir.glob("*.mp3") if p.is_file() and p.stat().st_size > 0),
                key=lambda p: p.stat().st_mtime,
            )
            if mp3_files:
                return mp3_files[-1]

        candidates: list[Path] = []
        for download in info.get("requested_downloads") or []:
            if filepath := download.get("filepath"):
                candidates.append(Path(filepath))
        if filepath := info.get("filepath"):
            candidates.append(Path(filepath))
        try:
            candidates.append(Path(ydl.prepare_filename(info)))
        except Exception:  # noqa: BLE001 - prepare_filename может падать на странных info
            pass

        for candidate in candidates:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate

        suffixes = {".mp3"} if kind == "audio" else _VIDEO_SUFFIXES
        files = [
            path
            for path in workdir.iterdir()
            if path.is_file() and path.suffix.lower() in suffixes and path.stat().st_size > 0
        ]
        if files:
            return max(files, key=lambda p: p.stat().st_mtime)

        raise DownloadFailed("После скачивания не найден готовый файл.")

    def _remux_mp4(self, source: Path) -> Path:
        if not self.ffmpeg:
            return source
        target = source.with_name(source.stem + ".remux.mp4")
        command = [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(target),
        ]
        try:
            result = subprocess.run(command, capture_output=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("remux failed: %s", exc)
            return source
        if result.returncode == 0 and target.is_file() and target.stat().st_size > 0:
            source.unlink(missing_ok=True)
            return target
        target.unlink(missing_ok=True)
        log.warning("remux failed: %s", result.stderr.decode("utf-8", "replace")[:300])
        return source

    def _prepare_thumbnail(self, workdir: Path, media: Path) -> Path | None:
        if not self.ffmpeg:
            return None
        images = [
            path
            for path in workdir.iterdir()
            if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
        ]
        if not images:
            return None
        source = max(images, key=lambda p: p.stat().st_size)
        target = workdir / "thumb.jpg"
        command = [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            "scale=320:-2",
            "-q:v",
            "5",
            str(target),
        ]
        try:
            result = subprocess.run(command, capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return None
        for image in images:
            image.unlink(missing_ok=True)
        if result.returncode == 0 and target.is_file() and target.stat().st_size > 0:
            return target
        target.unlink(missing_ok=True)
        return None

    def _translate(self, exc: BaseException, platform: str) -> DownloadFailed:
        cause = _find_cause(exc, (DownloadCancelled, FileTooLarge, DownloadFailed))
        if isinstance(cause, DownloadFailed):
            return cause
        if isinstance(cause, DownloadCancelled):
            raise cause

        text = str(exc)
        log.debug("yt-dlp error: %s", text)

        marker = re.search(r"DL_TOO_LARGE:(\d+):(\d+)", text, re.IGNORECASE)
        if marker:
            return FileTooLarge(int(marker.group(1)), int(marker.group(2)))
        if "DL_CANCELLED" in text.upper():
            raise DownloadCancelled()

        return DownloadFailed(_friendly_error(text, platform), technical=text[:2000])

    # ------------------------------------------------------------- Threads

    def _fetch_threads(
        self,
        *,
        url: str,
        kind: str,
        quality: int,
        workdir: Path,
        on_progress: ProgressCallback,
        cancel: threading.Event,
    ) -> MediaResult:
        media = self._threads.resolve(url)
        on_progress(Progress(stage="processing", title=media.title))

        max_bytes = self.settings.max_upload_bytes
        target = workdir / "threads.mp4"

        def direct_progress(downloaded: int, total: int) -> None:
            on_progress(
                Progress(
                    stage="downloading",
                    downloaded=downloaded,
                    total=total,
                    title=media.title,
                )
            )

        path, version = self._threads.download(
            media,
            target,
            max_bytes=max_bytes,
            cancel=cancel,
            on_progress=direct_progress,
        )

        if kind == "audio":
            if not self.ffmpeg:
                raise DownloadFailed(
                    "Для извлечения MP3 из Threads нужен ffmpeg. Установите его и перезапустите бота."
                )
            audio = workdir / "threads.mp3"
            self._extract_audio(path, audio, quality)
            if audio.stat().st_size > max_bytes:
                fitted = self._fit_audio_size(workdir, audio, quality)
                if fitted is not None:
                    audio = fitted
            path.unlink(missing_ok=True)
            path = audio

        size = path.stat().st_size
        if size > max_bytes:
            raise FileTooLarge(size, max_bytes)

        return MediaResult(
            path=path,
            kind=kind,
            platform="threads",
            title=media.title,
            source_url=url,
            size=size,
            uploader=media.author,
            duration=media.duration,
            width=version.width or None,
            height=version.height or None,
        )

    def _fit_audio_size(self, workdir: Path, current: Path, bitrate: int) -> Path | None:
        """Перекодирует MP3 в меньший битрейт, если исходник остался на диске."""
        sources = [
            path
            for path in workdir.iterdir()
            if path.is_file()
            and path != current
            and path.suffix.lower()
            in {".webm", ".m4a", ".opus", ".ogg", ".aac", ".mp4", ".mkv", ".flac"}
        ]
        if not sources:
            return None
        source = max(sources, key=lambda path: path.stat().st_size)

        limit = self.settings.max_upload_bytes
        for kbps in (value for value in AUDIO_BITRATES if value < bitrate):
            target = workdir / f"audio_{kbps}.mp3"
            try:
                self._extract_audio(source, target, kbps)
            except DownloadFailed:
                continue
            if target.stat().st_size <= limit:
                current.unlink(missing_ok=True)
                return target
            target.unlink(missing_ok=True)
        return None

    def _extract_audio(self, source: Path, target: Path, bitrate: int) -> None:
        command = [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vn",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-b:a",
            f"{bitrate}k",
            str(target),
        ]
        result = subprocess.run(command, capture_output=True, timeout=600)
        if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            raise DownloadFailed(
                "Не удалось извлечь аудио из видео.",
                technical=result.stderr.decode("utf-8", "replace")[:500],
            )
