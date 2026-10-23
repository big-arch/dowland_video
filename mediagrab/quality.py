"""Значения качества, общие для настроек и кнопок."""

BEST_VIDEO = 0  # Без ограничения разрешения, в том числе выше 4K.
VIDEO_OPTIONS = (BEST_VIDEO, 2160, 1440, 1080, 720, 480, 360)


def video_quality_label(height: int) -> str:
    if height == BEST_VIDEO:
        return "Лучшее доступное"
    if height == 2160:
        return "2160p · 4K"
    return f"{height}p"
