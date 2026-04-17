from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher

from app.settings import Settings
from bot.db import Database
from bot.exceptions import RuntimeValidationError
from bot.handlers import router
from bot.scheduler import scheduler_loop


async def run_bot(settings: Settings) -> None:
    if not settings.bot_token:
        raise RuntimeValidationError("BOT_TOKEN is required to start bot")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    db = Database(settings.database_url)
    await db.init()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    dp.include_router(router)
    dp["db"] = db
    dp["settings"] = settings

    scheduler_task = asyncio.create_task(scheduler_loop(bot, db))

    try:
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task
        await db.close()
        await bot.session.close()
