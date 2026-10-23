from __future__ import annotations

import json

from mediagrab.storage import UserPrefs, UserStore


async def test_defaults_are_created(tmp_path) -> None:
    path = tmp_path / "users.json"
    store = UserStore(path, UserPrefs(video_height=720, audio_kbps=192))
    prefs = await store.get(42)
    assert prefs.video_height == 720
    assert prefs.audio_kbps == 192
    assert prefs.send_as_document is False
    assert json.loads(path.read_text(encoding="utf-8"))["42"]["video_height"] == 720


async def test_update_persists(tmp_path) -> None:
    path = tmp_path / "users.json"
    store = UserStore(path, UserPrefs())
    await store.update(1, video_height=1080, audio_kbps=320, send_as_document=True)

    reloaded = UserStore(path, UserPrefs())
    prefs = await reloaded.get(1)
    assert prefs.video_height == 1080
    assert prefs.audio_kbps == 320
    assert prefs.send_as_document is True


async def test_unknown_keys_ignored(tmp_path) -> None:
    store = UserStore(tmp_path / "users.json", UserPrefs())
    prefs = await store.update(1, video_height=480, nonsense="x")
    assert prefs.video_height == 480


async def test_corrupted_file_survives(tmp_path) -> None:
    path = tmp_path / "users.json"
    path.write_text("{не json", encoding="utf-8")
    store = UserStore(path, UserPrefs(video_height=720))
    prefs = await store.get(5)
    assert prefs.video_height == 720
