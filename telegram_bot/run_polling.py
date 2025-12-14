import asyncio
from aiogram.types import BotCommand, BotCommandScopeDefault
from telegram_bot.bot_core import dp, bot

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
    await dp.start_polling(bot, allowed_updates=None)

if __name__ == "__main__":
    asyncio.run(main())
