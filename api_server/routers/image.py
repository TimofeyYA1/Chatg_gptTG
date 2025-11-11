from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db_adapter.database import get_db
from db_adapter.models import User, File
from api_server.providers.openai_adapter import OpenAIProvider

router = APIRouter()

class ImageIn(BaseModel):
    chat_id: int
    prompt: str
    size: str | None = "768x768"  # подешевле, чем 1024

@router.post("/generate")
def generate_image(data: ImageIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.chat_id == data.chat_id).first()
    if not user:
        user = User(chat_id=data.chat_id)
        db.add(user); db.commit(); db.refresh(user)

    provider = OpenAIProvider()
    b64 = provider.generate_image_b64(data.prompt, size=data.size or "768x768")
    if not b64:
        # мягкая заглушка
        return {"ok": True, "stub": True, "caption": "🖼️ (симуляция) Картинка сгенерирована."}

    # сохранять файл в сторадж сейчас не будем — вернём base64
    # (бот сможет отправить как фото через InputFile(BytesIO(...)))
    return {"ok": True, "stub": False, "b64": b64, "caption": data.prompt.strip()[:200]}
