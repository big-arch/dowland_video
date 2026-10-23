"""Исключения бота: отделяем технические ошибки от сообщений пользователю."""

from __future__ import annotations

from .utils import human_size


class BotError(Exception):
    """Ошибка, текст которой можно показать пользователю."""

    def __init__(self, user_message: str, *, technical: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical = technical


class DownloadFailed(BotError):
    """Не удалось скачать или обработать медиа."""


class FileTooLarge(DownloadFailed):
    def __init__(self, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        super().__init__(
            f"Файл весит {human_size(size)}, а лимит отправки — {human_size(limit)}.\n"
            "Попробуйте качество ниже или включите локальный Bot API сервер "
            "(см. README, раздел «Файлы больше 50 МБ»)."
        )

    def __str__(self) -> str:  # маркер, который переживает обёртки yt-dlp
        return f"DL_TOO_LARGE:{self.size}:{self.limit}"


class DownloadCancelled(Exception):
    """Пользователь отменил загрузку."""

    def __str__(self) -> str:  # маркер, который переживает обёртки yt-dlp
        return "DL_CANCELLED"


class BusyError(BotError):
    """У пользователя уже есть активная задача."""


class RateLimited(BotError):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Слишком часто. Попробуйте через {retry_after} с.")
