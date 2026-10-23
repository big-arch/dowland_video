"""Отрисовка прогресса загрузки для сообщения в Telegram."""

from __future__ import annotations

import html

from .downloader import Progress
from .texts import PLATFORM_ICONS, PLATFORM_LABELS
from .utils import human_duration, human_size, human_speed, progress_bar

_STAGE_TITLES = {
    "downloading": "⬇️ Скачиваю",
    "processing": "⚙️ Обрабатываю",
    "uploading": "📤 Отправляю",
}


def format_progress(progress: Progress, kind: str, platform: str) -> str:
    label = PLATFORM_LABELS.get(platform, platform)
    icon = PLATFORM_ICONS.get(platform, "🔗")
    what = "видео" if kind == "video" else "аудио"

    lines = [f"{icon} <b>{label}</b> · {what}"]
    stage = _STAGE_TITLES.get(progress.stage, "⬇️ Скачиваю")
    lines.append(f"{stage}…")

    if progress.total and progress.downloaded:
        percent = min(100.0, progress.downloaded * 100 / progress.total)
        lines.append(f"<code>{progress_bar(percent)}</code> {int(percent)}%")
        details = f"{human_size(progress.downloaded)} / {human_size(progress.total)}"
        if speed := human_speed(progress.speed):
            details += f" · {speed}"
        lines.append(details)
        if progress.eta is not None and progress.eta > 0:
            lines.append(f"⏳ осталось {human_duration(progress.eta)}")
    elif progress.downloaded:
        details = human_size(progress.downloaded)
        if speed := human_speed(progress.speed):
            details += f" · {speed}"
        lines.append(details)

    if progress.title:
        lines.append(f"<i>{html.escape(_short(progress.title))}</i>")

    return "\n".join(lines)


def _short(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
