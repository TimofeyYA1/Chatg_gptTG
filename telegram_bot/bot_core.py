"""
telegram_bot.bot_core

Сохраняем структуру проекта:
docker/entrypoint_bot.sh -> python -m telegram_bot.run_polling

Этот файл держит только:
- Bot/Dispatcher
- подключение роутеров
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from common.config import settings
from telegram_bot.routers.mylook import router as mylook_router

bot = Bot(
    token=settings.TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher(storage=MemoryStorage())
dp.include_router(mylook_router)
