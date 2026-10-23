"""Тесты оркестратора с фейковым Bot и Downloader (без сети)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

from mediagrab.config import Settings
from mediagrab.downloader import MediaResult, Progress
from mediagrab.errors import DownloadCancelled, DownloadFailed
from mediagrab.runner import Runner
from mediagrab.storage import UserPrefs, UserStore


class FakeUser:
    id = 1


class FakeChat:
    id = 100


class FakeStatus:
    message_id = 555


class FakeMessage:
    def __init__(self) -> None:
        self.from_user = FakeUser()
        self.chat = FakeChat()
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs):
        self.answers.append(text)
        return FakeStatus()


class FakeDownloader:
    def __init__(self, *, fail: str | None = None, block: bool = False) -> None:
        self.fail = fail
        self.block = block
        self.calls: list[dict] = []

    def fetch(self, **kwargs) -> MediaResult:
        self.calls.append(kwargs)
        on_progress = kwargs["on_progress"]
        cancel = kwargs["cancel"]

        if self.block:
            while not cancel.is_set():
                time.sleep(0.01)
            raise DownloadCancelled()

        if self.fail:
            raise DownloadFailed(self.fail)

        on_progress(Progress(stage="downloading", downloaded=5, total=10, speed=100, eta=1))
        path = Path(kwargs["workdir"]) / "media.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 32)
        return MediaResult(
            path=path,
            kind=kwargs["kind"],
            platform="youtube",
            title="Test clip",
            source_url="https://youtu.be/test",
            size=32,
            uploader="tester",
            duration=3,
            width=320,
            height=240,
        )


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        bot_token="",
        download_dir=tmp_path / "dl",
        data_dir=tmp_path / "data",
        cookies_dir=tmp_path / "cookies",
        max_upload_mb=50,
        max_concurrent=1,
        rate_limit_sec=0,
        default_video_height=720,
        default_audio_kbps=192,
        proxy=None,
        local_api_url=None,
        log_level="INFO",
        ffmpeg_path=None,
        js_runtime="none",
        threads_enabled=True,
    )


def make_runner(tmp_path: Path, downloader: FakeDownloader) -> tuple[Runner, AsyncMock]:
    settings = make_settings(tmp_path)
    store = UserStore(tmp_path / "data" / "users.json", UserPrefs())
    bot = AsyncMock()
    return Runner(bot, settings, store, downloader), bot


async def wait_idle(runner: Runner, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while runner.active_count and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert runner.active_count == 0


async def test_successful_video_job(tmp_path: Path) -> None:
    runner, bot = make_runner(tmp_path, FakeDownloader())
    message = FakeMessage()

    job = await runner.enqueue(
        message, url="https://youtu.be/test", platform="youtube", kind="video", quality=720
    )
    assert job.id
    assert message.answers and "Ставлю в очередь" in message.answers[0]

    await wait_idle(runner)

    assert runner.stats.success == 1
    assert bot.send_video.await_count == 1
    assert bot.delete_message.await_count == 1
    assert "Test clip" in str(bot.send_video.await_args.kwargs["caption"])


async def test_audio_job(tmp_path: Path) -> None:
    runner, bot = make_runner(tmp_path, FakeDownloader())
    message = FakeMessage()

    await runner.enqueue(
        message, url="https://youtu.be/test", platform="youtube", kind="audio", quality=192
    )
    await wait_idle(runner)

    assert bot.send_audio.await_count == 1
    assert runner.stats.success == 1


async def test_failure_shows_error(tmp_path: Path) -> None:
    runner, bot = make_runner(tmp_path, FakeDownloader(fail="Видео недоступно"))
    message = FakeMessage()

    await runner.enqueue(
        message, url="https://youtu.be/test", platform="youtube", kind="video", quality=720
    )
    await wait_idle(runner)

    assert runner.stats.failed == 1
    assert bot.send_video.await_count == 0
    edited = " ".join(str(call.kwargs.get("text", "")) for call in bot.edit_message_text.await_args_list)
    assert "Видео недоступно" in edited


async def test_cancel_running_job(tmp_path: Path) -> None:
    runner, bot = make_runner(tmp_path, FakeDownloader(block=True))
    message = FakeMessage()

    job = await runner.enqueue(
        message, url="https://youtu.be/test", platform="youtube", kind="video", quality=720
    )
    await asyncio.sleep(0.05)
    assert runner.cancel(job.id, 1) is True
    await wait_idle(runner)

    assert runner.stats.cancelled == 1
    assert bot.send_video.await_count == 0


async def test_busy_and_rate_limit(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), rate_limit_sec=60)
    store = UserStore(tmp_path / "data" / "users.json", UserPrefs())
    runner = Runner(AsyncMock(), settings, store, FakeDownloader(block=True))

    await runner.enqueue(
        FakeMessage(), url="https://youtu.be/1", platform="youtube", kind="video", quality=720
    )

    from mediagrab.errors import BusyError, RateLimited

    try:
        await runner.enqueue(
            FakeMessage(), url="https://youtu.be/2", platform="youtube", kind="video", quality=720
        )
    except (BusyError, RateLimited):
        pass
    else:
        raise AssertionError("вторая задача должна быть отклонена")

    assert runner.cancel_user(1) == 1
    await wait_idle(runner)
