import asyncio
import logging
import sys
from aiogram.types import (
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeAllPrivateChats,
)
from telegram_bot.bot_core import dp, bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _menu_commands() -> list[BotCommand]:
    return [
        BotCommand(command="start", description="🚀 Главное меню"),
        BotCommand(command="premium", description="⭐ Купить подписку"),
        BotCommand(command="account", description="🎁 Баланс и реферальная система"),
        BotCommand(command="packages", description="⭐️ Дополнительные генерации"),
        BotCommand(command="help", description="❓ Помощь"),
    ]


async def _sync_menu_commands(bot) -> None:
    commands = _menu_commands()
    scopes = [BotCommandScopeDefault(), BotCommandScopeAllPrivateChats()]
    languages = [None, "ru", "en"]

    for scope in scopes:
        for language_code in languages:
            try:
                await bot.delete_my_commands(scope=scope, language_code=language_code)
            except Exception:
                logger.debug(
                    "No commands to delete for scope=%s lang=%s",
                    type(scope).__name__,
                    language_code,
                )
            await bot.set_my_commands(
                commands,
                scope=scope,
                language_code=language_code,
            )


async def on_startup(bot):
    await _sync_menu_commands(bot)


dp.startup.register(on_startup)


async def main():
    await dp.start_polling(
        bot,
        allowed_updates=["message", "edited_message", "callback_query", "pre_checkout_query"],
    )


if __name__ == "__main__":
    asyncio.run(main())
