"""Точка входа: python -m mediagrab [--check] [--env-file .env]."""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import shutil
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from . import __version__
from .config import Settings, load_dotenv
from .downloader import Downloader
from .handlers import PendingStore, build_router
from .middleware import AccessMiddleware
from .runner import Runner
from .storage import UserPrefs, UserStore

log = logging.getLogger("mediagrab")


def setup_logging(level: str, log_file: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(
                RotatingFileHandler(
                    log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
                )
            )
        except OSError:
            pass

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def build_bot(settings: Settings) -> Bot:
    timeout = 1800 if settings.local_api_url else 600
    if settings.local_api_url:
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(settings.local_api_url),
            timeout=timeout,
        )
    else:
        session = AiohttpSession(timeout=timeout)

    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def run(settings: Settings) -> None:
    bot = build_bot(settings)
    dispatcher = Dispatcher()

    store = UserStore(
        settings.data_dir / "users.json",
        UserPrefs(
            video_height=settings.default_video_height,
            audio_kbps=settings.default_audio_kbps,
        ),
    )
    downloader = Downloader(settings)
    runner = Runner(bot, settings, store, downloader)
    pending = PendingStore()

    dispatcher.include_router(
        build_router(settings=settings, store=store, runner=runner, pending=pending)
    )

    access = AccessMiddleware(settings.allowed_user_ids)
    dispatcher.message.outer_middleware(access)
    dispatcher.callback_query.outer_middleware(access)

    me = await bot.get_me()
    log.info("MediaGrab %s запущен как @%s", __version__, me.username)
    log.info(
        "ffmpeg=%s, js_runtime=%s, лимит=%s МБ, слотов=%s",
        downloader.ffmpeg or "нет",
        ",".join(downloader.js_runtime or {}) or "нет",
        settings.max_upload_mb,
        settings.max_concurrent,
    )

    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Начать"),
                BotCommand(command="settings", description="Качество по умолчанию"),
                BotCommand(command="cancel", description="Отменить загрузку"),
                BotCommand(command="help", description="Помощь"),
            ]
        )
    except Exception:  # noqa: BLE001 - команды не критичны
        log.debug("Не удалось обновить список команд", exc_info=True)

    await bot.delete_webhook(drop_pending_updates=settings.drop_pending_updates)

    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            handle_signals=True,
        )
    finally:
        log.info("Останавливаюсь…")
        await runner.shutdown()
        await bot.session.close()


def run_check(settings: Settings) -> int:
    import aiogram
    import yt_dlp

    downloader = Downloader(settings)
    token_looks_ok = bool(
        re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{25,}", settings.bot_token or "")
    )

    def line(name: str, value: str, ok: bool | None = None) -> str:
        mark = "" if ok is None else ("  OK  " if ok else " FAIL ")
        return f"{name:<16}{value}{mark}"

    rows = [
        line("Python", sys.version.split()[0]),
        line("aiogram", aiogram.__version__),
        line("yt-dlp", yt_dlp.version.__version__),
        line("ffmpeg", downloader.ffmpeg or "не найден", bool(downloader.ffmpeg)),
        line(
            "JS runtime",
            ",".join(downloader.js_runtime or {}) or "не найден",
            bool(downloader.js_runtime),
        ),
        line(
            "BOT_TOKEN",
            "задан" if settings.bot_token else "не задан",
            token_looks_ok,
        ),
        line("Лимит файла", f"{settings.max_upload_mb} МБ"),
        line("Слотов", str(settings.max_concurrent)),
        line("Каталог данных", str(settings.data_dir.resolve())),
        line("Каталог cookies", str(settings.cookies_dir.resolve())),
    ]

    cookies = []
    for platform in ("youtube", "instagram", "tiktok", "threads", "x", "rutube", "vk"):
        path = settings.cookies_dir / f"{platform}.txt"
        cookies.append(f"{platform}:{'да' if path.is_file() else 'нет'}")
    rows.append(line("Cookies", ", ".join(cookies)))

    print(f"\nMediaGrab {__version__} — проверка окружения\n" + "─" * 62)
    for row in rows:
        print(row)
    print("─" * 62)

    if not token_looks_ok:
        print("BOT_TOKEN выглядит неправильно: ожидается формат 123456789:AA...")
        return 1
    if not downloader.ffmpeg:
        print("Без ffmpeg не будет MP3 и склейки видео. Установите ffmpeg.")
        return 1
    print("Всё готово: python -m mediagrab\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="mediagrab", description="Telegram-бот MediaGrab")
    parser.add_argument("--check", action="store_true", help="проверить окружение и выйти")
    parser.add_argument("--env-file", default=".env", help="путь к .env (по умолчанию .env)")
    args = parser.parse_args(argv)

    load_dotenv(Path(args.env_file))
    settings = Settings.from_env()
    settings.ensure_dirs()
    setup_logging(settings.log_level, settings.data_dir / "bot.log")

    if args.check:
        return run_check(settings)

    if not settings.bot_token:
        log.error("BOT_TOKEN не задан. Скопируйте .env.example в .env и вставьте токен.")
        return 2

    started = time.monotonic()
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        log.info("Прервано пользователем")
    except Exception:
        log.exception("Бот упал")
        return 1
    finally:
        log.info("Работа завершена за %.1f с", time.monotonic() - started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
