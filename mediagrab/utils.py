"""Мелкие утилиты: размеры, длительности, имена файлов, прогресс-бар."""

from __future__ import annotations

import re
import unicodedata

_UNITS = ("Б", "КБ", "МБ", "ГБ", "ТБ")
_BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SPACES = re.compile(r"\s+")


def human_size(num: float | int | None) -> str:
    """23_500_000 -> «22,4 МБ»."""
    if not num or num <= 0:
        return "0 Б"
    value = float(num)
    index = 0
    while value >= 1024 and index < len(_UNITS) - 1:
        value /= 1024
        index += 1
    if index == 0:
        return f"{int(value)} Б"
    return f"{value:.1f} {_UNITS[index]}".replace(".", ",")


def human_speed(bytes_per_sec: float | None) -> str:
    if not bytes_per_sec or bytes_per_sec <= 0:
        return ""
    return f"{human_size(bytes_per_sec)}/с"


def human_duration(seconds: float | int | None) -> str:
    """3725 -> «1:02:05», 95 -> «01:35»."""
    if seconds is None:
        return ""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def progress_bar(percent: float, width: int = 12) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = int(round(width * percent / 100))
    return "▓" * filled + "░" * (width - filled)


def safe_filename(name: str, *, max_length: int = 64, fallback: str = "media") -> str:
    """Убирает символы, недопустимые в именах файлов Telegram/Windows."""
    name = unicodedata.normalize("NFC", name or "")
    name = _BAD_FILENAME_CHARS.sub(" ", name)
    name = _SPACES.sub(" ", name).strip(" .")
    if not name:
        return fallback
    if len(name) > max_length:
        name = name[:max_length].rstrip(" .")
    return name or fallback


def clamp_text(text: str, limit: int, *, suffix: str = "…") -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))].rstrip() + suffix
