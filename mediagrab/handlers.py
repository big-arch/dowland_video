"""Хэндлеры: ссылки, выбор качества, настройки, отмена."""

from __future__ import annotations

import asyncio
import html
import logging
import secrets
import time
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from .config import Settings
from .errors import BotError
from .keyboards import (
    AUDIO_OPTIONS,
    VIDEO_OPTIONS,
    download_keyboard,
    quality_keyboard,
    settings_keyboard,
)
from .links import detect_platform, is_playlist_url, resolve_short_url, split_supported
from .runner import Runner
from .storage import UserStore
from .texts import (
    NOTHING_TO_CANCEL,
    UNSUPPORTED_LINK,
    WELCOME,
    error_text,
    help_text,
    link_card,
    settings_text,
)
from .utils import clamp_text

log = logging.getLogger(__name__)

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
_ALLOWED_VIDEO = set(VIDEO_OPTIONS) | {144, 240, 1440, 2160}
_ALLOWED_AUDIO = set(AUDIO_OPTIONS) | {64, 96, 256}
MIN_AUDIO_KBPS = 64
MAX_AUDIO_KBPS = 320


@dataclass(slots=True)
class PendingLink:
    url: str
    platform: str
    user_id: int
    created: float


class PendingStore:
    """Короткие токены для callback-кнопок (ссылки не влезают в callback_data)."""

    def __init__(self, ttl: int = 1800) -> None:
        self.ttl = ttl
        self._items: dict[str, PendingLink] = {}

    def add(self, url: str, platform: str, user_id: int) -> str:
        self._prune()
        token = secrets.token_urlsafe(9)
        self._items[token] = PendingLink(
            url=url, platform=platform, user_id=user_id, created=time.monotonic()
        )
        return token

    def get(self, token: str) -> PendingLink | None:
        item = self._items.get(token)
        if item is None:
            return None
        if time.monotonic() - item.created > self.ttl:
            self._items.pop(token, None)
            return None
        return item

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [
            token
            for token, item in self._items.items()
            if now - item.created > self.ttl
        ]
        for token in expired:
            self._items.pop(token, None)


def build_router(
    *,
    settings: Settings,
    store: UserStore,
    runner: Runner,
    pending: PendingStore,
) -> Router:
    router = Router(name="media")

    # ------------------------------------------------------------ команды

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        await message.answer(WELCOME, link_preview_options=_NO_PREVIEW)

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        await message.answer(
            help_text(settings.max_upload_mb), link_preview_options=_NO_PREVIEW
        )

    @router.message(Command("settings"))
    async def on_settings(message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        prefs = await store.get(user.id)
        await message.answer(
            settings_text(prefs.video_height, prefs.audio_kbps, prefs.send_as_document),
            reply_markup=settings_keyboard(prefs),
            link_preview_options=_NO_PREVIEW,
        )

    @router.message(Command("cancel"))
    async def on_cancel(message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        count = runner.cancel_user(user.id)
        await message.answer(
            "⏹ Отменяю загрузку…" if count else NOTHING_TO_CANCEL
        )

    @router.message(Command("stats"))
    async def on_stats(message: Message) -> None:
        user = message.from_user
        if user is None or not settings.admin_ids or user.id not in settings.admin_ids:
            await message.answer("⛔️ Команда только для администратора.")
            return
        await message.answer(runner.status_line())

    @router.message(Command("id"))
    async def on_id(message: Message) -> None:
        if message.from_user:
            await message.answer(f"Ваш ID: <code>{message.from_user.id}</code>")

    # -------------------------------------------------------------- ссылки

    @router.message(F.text & ~F.text.startswith("/"))
    async def on_text(message: Message) -> None:
        user = message.from_user
        if user is None or not message.text:
            return

        supported, unsupported = split_supported(message.text)
        if not supported:
            if unsupported:
                listing = "\n".join(
                    f"• <code>{html.escape(clamp_text(url, 90))}</code>"
                    for url in unsupported[:3]
                )
                await message.answer(
                    f"{UNSUPPORTED_LINK}\n\nНе поддерживаются:\n{listing}",
                    link_preview_options=_NO_PREVIEW,
                )
            else:
                await message.answer(UNSUPPORTED_LINK, link_preview_options=_NO_PREVIEW)
            return

        url = supported[0]
        if is_playlist_url(url):
            await message.answer(
                "Плейлисты пока не поддерживаю — пришлите ссылку на конкретное видео."
            )
            return

        resolved = await asyncio.to_thread(
            resolve_short_url, url, proxy=settings.proxy
        )
        platform = detect_platform(resolved)
        if platform is None:
            await message.answer(UNSUPPORTED_LINK, link_preview_options=_NO_PREVIEW)
            return

        prefs = await store.get(user.id)
        token = pending.add(resolved, platform, user.id)
        await message.answer(
            link_card(platform, resolved, ignored=max(0, len(supported) - 1)),
            reply_markup=download_keyboard(token, prefs),
            link_preview_options=_NO_PREVIEW,
        )

    # ------------------------------------------------------------ callbacks

    async def _start_download(
        call: CallbackQuery, token: str, kind: str, raw_quality: int
    ) -> None:
        if call.message is None:
            await call.answer("Сообщение устарело.", show_alert=True)
            return

        item = pending.get(token)
        if item is None:
            await call.answer("Ссылка устарела, отправьте её заново.", show_alert=True)
            return
        if item.user_id != call.from_user.id:
            await call.answer("Это не ваша ссылка.", show_alert=True)
            return

        if kind == "v":
            quality = raw_quality if raw_quality in _ALLOWED_VIDEO else 720
            media_kind = "video"
        elif kind == "a":
            quality = min(max(raw_quality, MIN_AUDIO_KBPS), MAX_AUDIO_KBPS)
            media_kind = "audio"
        else:
            await call.answer("Некорректный формат.", show_alert=True)
            return

        await call.answer()
        try:
            await runner.enqueue(
                call.message,
                url=item.url,
                platform=item.platform,
                kind=media_kind,
                quality=quality,
            )
        except BotError as exc:
            await call.message.answer(error_text(exc))
            return

        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass

    @router.callback_query(F.data.startswith("dl:"))
    async def on_download(call: CallbackQuery) -> None:
        if call.data is None:
            return
        try:
            _, token, kind, raw_quality = call.data.split(":")
            quality = int(raw_quality)
        except (ValueError, TypeError):
            await call.answer("Некорректная кнопка.", show_alert=True)
            return
        await _start_download(call, token, kind, quality)

    @router.callback_query(F.data.startswith("q:"))
    async def on_quality(call: CallbackQuery) -> None:
        if call.data is None:
            return
        try:
            _, token, kind, raw_quality = call.data.split(":")
            quality = int(raw_quality)
        except (ValueError, TypeError):
            await call.answer("Некорректная кнопка.", show_alert=True)
            return
        await _start_download(call, token, kind, quality)

    @router.callback_query(F.data.startswith("more:"))
    async def on_more(call: CallbackQuery) -> None:
        if call.message is None or call.data is None:
            return
        token = call.data.split(":", 1)[1]
        item = pending.get(token)
        if item is None:
            await call.answer("Ссылка устарела, отправьте её заново.", show_alert=True)
            return
        await call.answer()
        try:
            await call.message.edit_text(
                link_card(item.platform, item.url),
                reply_markup=quality_keyboard(token),
            )
        except TelegramAPIError as exc:
            log.debug("edit failed: %s", exc)

    @router.callback_query(F.data.startswith("back:"))
    async def on_back(call: CallbackQuery) -> None:
        if call.message is None or call.data is None:
            return
        token = call.data.split(":", 1)[1]
        item = pending.get(token)
        if item is None:
            await call.answer("Ссылка устарела, отправьте её заново.", show_alert=True)
            return
        prefs = await store.get(call.from_user.id)
        await call.answer()
        try:
            await call.message.edit_text(
                link_card(item.platform, item.url),
                reply_markup=download_keyboard(token, prefs),
            )
        except TelegramAPIError as exc:
            log.debug("edit failed: %s", exc)

    @router.callback_query(F.data == "close")
    async def on_close(call: CallbackQuery) -> None:
        await call.answer()
        if call.message:
            try:
                await call.message.delete()
            except TelegramAPIError:
                pass

    @router.callback_query(F.data.startswith("cancel:"))
    async def on_cancel_job(call: CallbackQuery) -> None:
        if call.data is None:
            return
        job_id = call.data.split(":", 1)[1]
        if runner.cancel(job_id, call.from_user.id):
            await call.answer("Отменяю…")
        else:
            await call.answer("Задача уже завершена.", show_alert=True)

    # ------------------------------------------------------------ настройки

    @router.callback_query(F.data.startswith("st:"))
    async def on_setting_change(call: CallbackQuery) -> None:
        if call.message is None or call.data is None:
            return
        parts = call.data.split(":")
        if len(parts) < 2:
            return
        field = parts[1]

        if field == "close":
            await call.answer()
            try:
                await call.message.delete()
            except TelegramAPIError:
                pass
            return

        if len(parts) < 3 or not parts[2].isdigit():
            await call.answer("Некорректное значение.", show_alert=True)
            return
        value = int(parts[2])

        if field == "v" and value in _ALLOWED_VIDEO:
            prefs = await store.update(call.from_user.id, video_height=value)
        elif field == "a" and value in _ALLOWED_AUDIO:
            prefs = await store.update(call.from_user.id, audio_kbps=value)
        elif field == "doc" and value in (0, 1):
            prefs = await store.update(call.from_user.id, send_as_document=bool(value))
        else:
            await call.answer("Некорректное значение.", show_alert=True)
            return

        await call.answer("Сохранено")
        try:
            await call.message.edit_text(
                settings_text(prefs.video_height, prefs.audio_kbps, prefs.send_as_document),
                reply_markup=settings_keyboard(prefs),
            )
        except TelegramAPIError as exc:
            log.debug("settings edit failed: %s", exc)

    return router
