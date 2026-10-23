"""Ограничение доступа к боту по списку пользователей."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from .texts import PRIVATE_BOT


class AccessMiddleware(BaseMiddleware):
    def __init__(self, allowed_user_ids: frozenset[int]) -> None:
        self.allowed = allowed_user_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self.allowed:
            return await handler(event, data)

        user = data.get("event_from_user")
        if user is not None and user.id in self.allowed:
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer(PRIVATE_BOT)
        elif isinstance(event, CallbackQuery):
            await event.answer(PRIVATE_BOT, show_alert=True)
        return None
