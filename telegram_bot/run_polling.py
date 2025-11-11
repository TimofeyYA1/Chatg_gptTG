
import asyncio
from telegram_bot.bot_core import dp, bot

async def main():
    await dp.start_polling(bot, allowed_updates=None)

if __name__ == "__main__":
    asyncio.run(main())
