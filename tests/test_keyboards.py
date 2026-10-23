from __future__ import annotations

from mediagrab.handlers import PendingStore
from mediagrab.keyboards import (
    cancel_keyboard,
    download_keyboard,
    quality_keyboard,
    settings_keyboard,
)
from mediagrab.storage import UserPrefs


def _all_callbacks(markup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


def test_callback_data_fits_telegram_limit() -> None:
    token = "AbCdEfGhIjKl"
    prefs = UserPrefs()
    markups = [
        download_keyboard(token, prefs),
        quality_keyboard(token),
        settings_keyboard(prefs),
        cancel_keyboard("deadbeef"),
    ]
    for markup in markups:
        for data in _all_callbacks(markup):
            assert len(data.encode("utf-8")) <= 64, data


def test_download_keyboard_has_defaults() -> None:
    prefs = UserPrefs(video_height=1080, audio_kbps=320)
    callbacks = _all_callbacks(download_keyboard("tok", prefs))
    assert "dl:tok:v:1080" in callbacks
    assert "dl:tok:a:320" in callbacks


def test_settings_keyboard_marks_current() -> None:
    markup = settings_keyboard(UserPrefs(video_height=480, audio_kbps=128))
    texts = [button.text for row in markup.inline_keyboard for button in row]
    assert "✅ 480p" in texts
    assert "✅ 128" in texts
    assert any("Отправлять файлом" in text for text in texts)


def test_best_and_4k_available_in_both_menus():
    for keyboard, prefix in [(quality_keyboard("tok"), "q:tok:v:"),
                             (settings_keyboard(UserPrefs()), "st:v:")]:
        callbacks = _all_callbacks(keyboard)
        for value in (0, 2160, 1440):
            assert f"{prefix}{value}" in callbacks
    label = download_keyboard("tok", UserPrefs(video_height=0)).inline_keyboard[0][0].text
    assert "Лучшее доступное" in label
    assert "0p" not in label


class TestPendingStore:
    def test_add_and_get(self) -> None:
        store = PendingStore(ttl=60)
        token = store.add("https://youtu.be/1", "youtube", 7)
        item = store.get(token)
        assert item is not None
        assert item.user_id == 7
        assert item.platform == "youtube"

    def test_expires(self) -> None:
        store = PendingStore(ttl=0)
        token = store.add("https://youtu.be/1", "youtube", 7)
        assert store.get(token) is None

    def test_unknown_token(self) -> None:
        assert PendingStore().get("nope") is None
