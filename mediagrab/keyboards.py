"""Inline-клавиатуры."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .storage import UserPrefs
from .quality import VIDEO_OPTIONS, video_quality_label

AUDIO_OPTIONS = (320, 192, 128)


def download_keyboard(token: str, prefs: UserPrefs) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🎬 Видео · {video_quality_label(prefs.video_height)}",
        callback_data=f"dl:{token}:v:{prefs.video_height}",
    )
    builder.button(
        text=f"🎵 MP3 · {prefs.audio_kbps}",
        callback_data=f"dl:{token}:a:{prefs.audio_kbps}",
    )
    builder.button(text="⚙️ Другое качество", callback_data=f"more:{token}")
    builder.button(text="✖️ Закрыть", callback_data="close")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def quality_keyboard(token: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for height in VIDEO_OPTIONS:
        builder.button(text=f"🎬 {video_quality_label(height)}", callback_data=f"q:{token}:v:{height}")
    for kbps in AUDIO_OPTIONS:
        builder.button(text=f"🎵 {kbps} kbps", callback_data=f"q:{token}:a:{kbps}")
    builder.button(text="← Назад", callback_data=f"back:{token}")
    builder.adjust(1, 3, 3, 3, 1)
    return builder.as_markup()


def cancel_keyboard(job_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⏹ Отменить", callback_data=f"cancel:{job_id}")
    return builder.as_markup()


def settings_keyboard(prefs: UserPrefs) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for height in VIDEO_OPTIONS:
        mark = "✅ " if height == prefs.video_height else ""
        builder.button(text=f"{mark}{video_quality_label(height)}", callback_data=f"st:v:{height}")
    for kbps in AUDIO_OPTIONS:
        mark = "✅ " if kbps == prefs.audio_kbps else ""
        builder.button(text=f"{mark}{kbps}", callback_data=f"st:a:{kbps}")
    doc_mark = "✅ " if prefs.send_as_document else ""
    doc_next = 0 if prefs.send_as_document else 1
    builder.button(
        text=f"{doc_mark}📎 Отправлять файлом",
        callback_data=f"st:doc:{doc_next}",
    )
    builder.button(text="✖️ Закрыть", callback_data="st:close")
    builder.adjust(1, 3, 3, 3, 1, 1)
    return builder.as_markup()
