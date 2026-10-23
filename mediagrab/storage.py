"""Настройки пользователей в JSON-файле."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)


@dataclass(slots=True)
class UserPrefs:
    video_height: int = 720
    audio_kbps: int = 192
    send_as_document: bool = False


class UserStore:
    """Простое хранилище: data/users.json, атомарная запись."""

    def __init__(self, path: Path, defaults: UserPrefs) -> None:
        self.path = path
        self.defaults = defaults
        self._lock = asyncio.Lock()
        self._cache: dict[int, UserPrefs] = {}
        self._loaded = False

    def _load_sync(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._cache = {}
            return
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Не удалось прочитать %s: %s", self.path, exc)
            self._cache = {}
            return

        cache: dict[int, UserPrefs] = {}
        for key, value in raw.items():
            if not str(key).isdigit() or not isinstance(value, dict):
                continue
            cache[int(key)] = UserPrefs(
                video_height=int(value.get("video_height", self.defaults.video_height)),
                audio_kbps=int(value.get("audio_kbps", self.defaults.audio_kbps)),
                send_as_document=bool(value.get("send_as_document", False)),
            )
        self._cache = cache

    def _save_sync(self) -> None:
        payload = {str(uid): asdict(prefs) for uid, prefs in self._cache.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.path)

    async def get(self, user_id: int) -> UserPrefs:
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load_sync)
                self._loaded = True
            prefs = self._cache.get(user_id)
            if prefs is None:
                prefs = UserPrefs(
                    video_height=self.defaults.video_height,
                    audio_kbps=self.defaults.audio_kbps,
                )
                self._cache[user_id] = prefs
                await asyncio.to_thread(self._save_sync)
            return UserPrefs(**asdict(prefs))

    async def update(self, user_id: int, **changes) -> UserPrefs:
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load_sync)
                self._loaded = True
            current = self._cache.get(user_id) or UserPrefs(
                video_height=self.defaults.video_height,
                audio_kbps=self.defaults.audio_kbps,
            )
            for key, value in changes.items():
                if hasattr(current, key):
                    setattr(current, key, value)
            self._cache[user_id] = current
            await asyncio.to_thread(self._save_sync)
            return UserPrefs(**asdict(current))
