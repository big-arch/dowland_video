"""Тексты интерфейса и подписи к медиа."""

from __future__ import annotations

import html

from .errors import BotError
from .quality import video_quality_label
from .utils import clamp_text, human_duration, human_size

PLATFORM_LABELS: dict[str, str] = {
    "youtube": "YouTube",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "threads": "Threads",
    "x": "X (Twitter)",
    "rutube": "Rutube",
    "vk": "VK Video",
}

PLATFORM_ICONS: dict[str, str] = {
    "youtube": "▶️",
    "instagram": "📸",
    "tiktok": "🎵",
    "threads": "🧵",
    "x": "✖️",
    "rutube": "🎥",
    "vk": "🅥",
}

PLATFORM_LIST = "\n".join(
    f"{PLATFORM_ICONS[key]} {label}" for key, label in PLATFORM_LABELS.items()
)

WELCOME = (
    "<b>MediaGrab</b> — скачиваю видео и музыку по ссылке.\n\n"
    "<b>Поддерживаются:</b>\n"
    f"{PLATFORM_LIST}\n\n"
    "Пришлите ссылку — покажу варианты качества.\n"
    "Настройки: /settings · Помощь: /help"
)


def help_text(max_upload_mb: int) -> str:
    return (
        "<b>Как пользоваться</b>\n"
        "1. Скопируйте ссылку на видео, пост или трек.\n"
        "2. Отправьте её в этот чат.\n"
        "3. Выберите «Видео» или «Аудио».\n\n"
        "<b>Ограничения</b>\n"
        f"• Файл до {max_upload_mb} МБ — лимит Telegram Bot API.\n"
        "• «Лучшее доступное» — максимальное качество исходника, без перекодирования видео.\n"
        "• Если видео больше лимита, качество автоматически не снижается.\n"
        "• Плейлисты и карусели: скачиваю только первый элемент.\n"
        "• Instagram, TikTok и X часто требуют cookies — положите "
        "<code>cookies/instagram.txt</code> и т. п. (см. README).\n"
        "• YouTube может попросить подтвердить, что вы не робот — тоже лечится cookies.\n\n"
        "<b>Команды</b>\n"
        "/settings — качество по умолчанию\n"
        "/cancel — отменить текущую загрузку\n"
        "/help — эта справка\n\n"
        "Файлы удаляются с сервера сразу после отправки."
    )


SETTINGS_TITLE = "<b>⚙️ Настройки</b>\n\nВыберите значения по умолчанию:"


def settings_text(video_height: int, audio_kbps: int, send_as_document: bool) -> str:
    doc = "да" if send_as_document else "нет"
    return (
        f"{SETTINGS_TITLE}\n\n"
        f"🎬 Видео: <b>{video_quality_label(video_height)}</b>\n"
        f"🎵 Аудио: <b>{audio_kbps} kbps</b>\n"
        f"📎 Отправлять видео файлом: <b>{doc}</b>"
    )


def link_card(platform: str, url: str, *, ignored: int = 0) -> str:
    label = PLATFORM_LABELS.get(platform, platform)
    icon = PLATFORM_ICONS.get(platform, "🔗")
    text = (
        f"{icon} <b>{label}</b>\n"
        f"<a href=\"{html.escape(url, quote=True)}\">ссылка</a>\n\n"
        "Что скачать?"
    )
    if ignored:
        text += f"\n\n<i>Остальные ссылки в сообщении пропущены ({ignored}).</i>"
    return text


def status_text(platform: str, kind: str, stage: str) -> str:
    label = PLATFORM_LABELS.get(platform, platform)
    what = "видео" if kind == "video" else "аудио"
    return f"<b>{label}</b> · {what}\n{stage}"


def build_caption(
    *,
    title: str,
    uploader: str,
    duration: int | None,
    platform: str,
    size: int,
    source_url: str,
    kind: str,
) -> str:
    label = PLATFORM_LABELS.get(platform, platform)
    parts: list[str] = []
    if uploader:
        parts.append(html.escape(clamp_text(uploader, 60)))
    if duration:
        parts.append(human_duration(duration))
    parts.append(human_size(size))
    parts.append(label)

    title = clamp_text(title or "Без названия", 180)
    caption = f"<b>{html.escape(title)}</b>\n" + " · ".join(parts)
    if kind == "video":
        caption += f'\n<a href="{html.escape(source_url, quote=True)}">Источник</a>'
    return clamp_text(caption, 1000)


def error_text(exc: BotError) -> str:
    return f"❌ {html.escape(exc.user_message)}"


UNSUPPORTED_LINK = (
    "Не понял ссылку. Поддерживаются YouTube, Instagram, TikTok, Threads, "
    "X, Rutube и VK Video.\n\nПришлите прямую ссылку на видео или пост."
)

PRIVATE_BOT = "🔒 Этот бот приватный."

CANCELLED = "⏹ Загрузка отменена."

NOTHING_TO_CANCEL = "Нет активных загрузок."

NO_FFMPEG = (
    "Для MP3 и склейки видео нужен ffmpeg. Установите его и перезапустите бота "
    "(см. README)."
)
