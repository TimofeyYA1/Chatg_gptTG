from fastapi import APIRouter, Request
router = APIRouter()

@router.post("/bot/webhook")
async def telegram_webhook(request: Request):
    from telegram_bot.bot_core import process_update_fastapi  # лениво
    data = await request.json()
    await process_update_fastapi(data)
    return {"ok": True}
