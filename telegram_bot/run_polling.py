import asyncio
import logging
import sys
from aiogram.types import BotCommand, BotCommandScopeDefault
from telegram_bot.bot_core import dp, bot

# Базовая настройка логирования для бота
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

async def on_startup(bot):
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="🚀 Главное меню"),
            BotCommand(command="premium", description="⭐ Купить подписку"),
            BotCommand(command="account", description="🎁 Баланс и реферальная система"),
            BotCommand(command="help", description="❓ Помощь"),
        ],
        scope=BotCommandScopeDefault(),
    )

dp.startup.register(on_startup)

async def main():
    await dp.start_polling(bot, allowed_updates=["message", "edited_message", "callback_query", "pre_checkout_query"])

if __name__ == "__main__":
    asyncio.run(main())
