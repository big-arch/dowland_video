"""Очередь задач, прогресс и отправка файлов в Telegram."""

from __future__ import annotations

import asyncio
import logging
import math
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import FSInputFile, LinkPreviewOptions, Message

from .config import Settings
from .downloader import Downloader, MediaResult, Progress
from .errors import (
    BotError,
    BusyError,
    DownloadCancelled,
    DownloadFailed,
    RateLimited,
)
from .formatting import format_progress
from .keyboards import cancel_keyboard
from .storage import UserStore
from .texts import build_caption, error_text, status_text
from .utils import clamp_text, human_duration, human_size, safe_filename

log = logging.getLogger(__name__)

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


@dataclass(slots=True)
class Job:
    id: str
    user_id: int
    chat_id: int
    url: str
    platform: str
    kind: str
    quality: int
    message_id: int | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    created: float = field(default_factory=time.time)


@dataclass(slots=True)
class Stats:
    started: float
    success: int = 0
    failed: int = 0
    cancelled: int = 0
    bytes_sent: int = 0


class Runner:
    def __init__(
        self,
        bot: Bot,
        settings: Settings,
        store: UserStore,
        downloader: Downloader,
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.store = store
        self.downloader = downloader
        self.stats = Stats(started=time.time())

        self._sem = asyncio.Semaphore(settings.max_concurrent)
        self._jobs: dict[str, Job] = {}
        self._active: dict[int, str] = {}
        self._last_started: dict[int, float] = {}
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ API

    @property
    def active_count(self) -> int:
        return len(self._jobs)

    async def enqueue(
        self,
        message: Message,
        *,
        url: str,
        platform: str,
        kind: str,
        quality: int,
    ) -> Job:
        user = message.from_user
        if user is None:
            raise BotError("Не удалось определить пользователя.")

        now = time.monotonic()
        last = self._last_started.get(user.id)
        if last is not None and self.settings.rate_limit_sec > 0:
            elapsed = now - last
            if elapsed < self.settings.rate_limit_sec:
                raise RateLimited(math.ceil(self.settings.rate_limit_sec - elapsed))

        if user.id in self._active:
            raise BusyError(
                "У вас уже есть активная загрузка. Дождитесь её окончания "
                "или отправьте /cancel."
            )

        job = Job(
            id=secrets.token_hex(4),
            user_id=user.id,
            chat_id=message.chat.id,
            url=url,
            platform=platform,
            kind=kind,
            quality=quality,
        )

        status = await message.answer(
            status_text(platform, kind, "⏳ Ставлю в очередь…"),
            reply_markup=cancel_keyboard(job.id),
            link_preview_options=_NO_PREVIEW,
        )
        job.message_id = status.message_id

        self._jobs[job.id] = job
        self._active[user.id] = job.id
        self._last_started[user.id] = now

        task = asyncio.create_task(self._run(job), name=f"job-{job.id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def cancel(self, job_id: str, user_id: int | None = None) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if user_id is not None and job.user_id != user_id:
            return False
        job.cancel.set()
        return True

    def cancel_user(self, user_id: int) -> int:
        cancelled = 0
        for job in self._jobs.values():
            if job.user_id == user_id and not job.cancel.is_set():
                job.cancel.set()
                cancelled += 1
        return cancelled

    def has_active(self, user_id: int) -> bool:
        return user_id in self._active

    async def shutdown(self) -> None:
        for job in self._jobs.values():
            job.cancel.set()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # --------------------------------------------------------------- worker

    async def _run(self, job: Job) -> None:
        workdir = self.settings.download_dir / job.id
        try:
            if job.cancel.is_set():
                raise DownloadCancelled()

            if self._sem.locked():
                await self._edit(
                    job,
                    status_text(job.platform, job.kind, "⏳ Жду свободный слот…"),
                    cancel_keyboard(job.id),
                )

            # Ждём слот короткими интервалами, чтобы отмена в очереди срабатывала сразу.
            while True:
                if job.cancel.is_set():
                    raise DownloadCancelled()
                try:
                    await asyncio.wait_for(self._sem.acquire(), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    continue

            try:
                if job.cancel.is_set():
                    raise DownloadCancelled()
                await self._edit(
                    job,
                    status_text(job.platform, job.kind, "⬇️ Скачиваю…"),
                    cancel_keyboard(job.id),
                )
                result = await self._download(job, workdir)
            finally:
                self._sem.release()

            if job.cancel.is_set():
                raise DownloadCancelled()

            await self._edit(
                job,
                status_text(job.platform, job.kind, "📤 Отправляю в Telegram…"),
                cancel_keyboard(job.id),
            )
            await self._send(job, result)

            self.stats.success += 1
            self.stats.bytes_sent += result.size
            await self._delete_status(job)
            log.info(
                "job %s done: %s %s %s",
                job.id,
                job.platform,
                job.kind,
                human_size(result.size),
            )

        except DownloadCancelled:
            self.stats.cancelled += 1
            log.info("job %s cancelled", job.id)
            await self._edit(job, "⏹ <b>Загрузка отменена</b>")

        except BotError as exc:
            self.stats.failed += 1
            log.warning("job %s failed: %s", job.id, exc.technical or exc.user_message)
            await self._edit(job, error_text(exc))

        except Exception:
            self.stats.failed += 1
            log.exception("job %s crashed", job.id)
            await self._edit(job, "❌ Внутренняя ошибка. Попробуйте ещё раз.")

        finally:
            self._jobs.pop(job.id, None)
            self._active.pop(job.user_id, None)
            if not self.settings.keep_files:
                await asyncio.to_thread(shutil.rmtree, workdir, True)

    async def _download(self, job: Job, workdir: Path) -> MediaResult:
        queue: asyncio.Queue[Progress] = asyncio.Queue(maxsize=32)
        loop = asyncio.get_running_loop()

        def on_progress(progress: Progress) -> None:
            def push() -> None:
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(progress)

            try:
                loop.call_soon_threadsafe(push)
            except RuntimeError:  # цикл уже закрыт
                pass

        pump = asyncio.create_task(self._pump(job, queue))
        try:
            return await asyncio.to_thread(
                self.downloader.fetch,
                url=job.url,
                platform=job.platform,
                kind=job.kind,
                quality=job.quality,
                workdir=workdir,
                on_progress=on_progress,
                cancel=job.cancel,
            )
        finally:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)

    async def _pump(self, job: Job, queue: asyncio.Queue[Progress]) -> None:
        last_edit = 0.0
        while True:
            progress = await queue.get()
            now = time.monotonic()
            if now - last_edit < 2.0:
                continue
            last_edit = now
            await self._edit(
                job,
                format_progress(progress, job.kind, job.platform),
                cancel_keyboard(job.id),
            )

    # -------------------------------------------------------------- sending

    async def _send(self, job: Job, result: MediaResult) -> None:
        prefs = await self.store.get(job.user_id)
        caption = build_caption(
            title=result.title,
            uploader=result.uploader,
            duration=result.duration,
            platform=result.platform,
            size=result.size,
            source_url=result.source_url,
            kind=result.kind,
        )

        title = clamp_text(" ".join((result.title or "media").split()), 60)
        filename = safe_filename(title, max_length=60) + "." + result.ext
        document = FSInputFile(result.path, filename=filename)
        thumbnail = None
        if result.thumbnail and result.thumbnail.exists():
            thumbnail = FSInputFile(result.thumbnail, filename="thumb.jpg")

        if result.kind == "audio":
            try:
                await self.bot.send_audio(
                    chat_id=job.chat_id,
                    audio=document,
                    title=title,
                    performer=clamp_text(result.uploader or "MediaGrab", 60),
                    duration=result.duration or None,
                    caption=caption,
                    thumbnail=thumbnail,
                )
            except TelegramBadRequest as exc:
                if "too big" in str(exc).lower():
                    raise DownloadFailed(
                        "Telegram не принял файл: превышен лимит размера. "
                        "Попробуйте качество ниже."
                    ) from exc
                log.warning("send_audio failed (%s), fallback to document", exc)
                await self._send_document(job, document, caption, thumbnail)
            return

        if (prefs.send_as_document or job.quality == 0 or job.quality >= 1440
                or result.ext not in {"mp4", "m4v", "mov"}):
            await self._send_document(job, document, caption, thumbnail)
            return

        try:
            await self.bot.send_video(
                chat_id=job.chat_id,
                video=document,
                caption=caption,
                duration=result.duration or None,
                width=result.width or None,
                height=result.height or None,
                supports_streaming=True,
                thumbnail=thumbnail,
            )
        except TelegramBadRequest as exc:
            if "too big" in str(exc).lower():
                raise DownloadFailed(
                    "Telegram не принял файл: превышен лимит размера. "
                    "Попробуйте качество ниже."
                ) from exc
            log.warning("send_video failed (%s), fallback to document", exc)
            await self._send_document(job, document, caption, thumbnail)

    async def _send_document(
        self,
        job: Job,
        document: FSInputFile,
        caption: str,
        thumbnail: FSInputFile | None,
    ) -> None:
        try:
            await self.bot.send_document(
                chat_id=job.chat_id,
                document=document,
                caption=caption,
                thumbnail=thumbnail,
            )
        except TelegramBadRequest as exc:
            if "too big" in str(exc).lower():
                raise DownloadFailed(
                    "Telegram не принял файл: превышен лимит размера."
                ) from exc
            raise DownloadFailed(f"Telegram отклонил файл: {exc.message}") from exc

    # --------------------------------------------------------------- helpers

    async def _edit(self, job: Job, text: str, markup=None) -> None:
        if not job.message_id:
            return
        try:
            await self.bot.edit_message_text(
                chat_id=job.chat_id,
                message_id=job.message_id,
                text=text,
                reply_markup=markup,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            log.debug("edit status failed: %s", exc)
        except TelegramAPIError as exc:
            log.debug("edit status failed: %s", exc)

    async def _delete_status(self, job: Job) -> None:
        if not job.message_id:
            return
        try:
            await self.bot.delete_message(job.chat_id, job.message_id)
        except TelegramAPIError:
            pass

    def status_line(self) -> str:
        uptime = human_duration(time.time() - self.stats.started)
        return (
            f"<b>📊 Статистика</b>\n"
            f"Аптайм: {uptime}\n"
            f"Успешно: {self.stats.success}\n"
            f"Ошибок: {self.stats.failed}\n"
            f"Отменено: {self.stats.cancelled}\n"
            f"Отправлено: {human_size(self.stats.bytes_sent)}\n"
            f"Активных задач: {self.active_count}"
        )
