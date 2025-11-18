from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db_adapter.database import get_db
from db_adapter.models import User, File
from api_server.providers.openai_adapter import OpenAIProvider
import base64

router = APIRouter()


class ImageIn(BaseModel):
    chat_id: int
    prompt: str
    size: str | None = "768x768"  # экономный размер


class ImageEditIn(BaseModel):
    chat_id: int
    prompt: str
    image_b64: str                 # исходное фото в base64
    size: str | None = "768x768"


@router.post("/generate")
def generate_image(data: ImageIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.chat_id == data.chat_id).first()
    if not user:
        user = User(chat_id=data.chat_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    provider = OpenAIProvider()
    b64 = provider.generate_image_b64(data.prompt, size=data.size or "1024x1024")
    if not b64:
        # мягкая заглушка
        return {
            "ok": True,
            "stub": True,
            "caption": "🖼️ (симуляция) Картинка сгенерирована."
        }

    return {
        "ok": True,
        "stub": False,
        "b64": b64,
        "caption": data.prompt.strip(),
    }


@router.post("/edit")
def edit_image(data: ImageEditIn, db: Session = Depends(get_db)):
    """
    Редактирование уже загруженного пользователем фото по текстовому промпту.
    Новый пайплайн:
      1) Улучшаем промпт через ChatGPT (OpenAI).
      2) Пытаемся отредактировать фото через NanoBanana с улучшенным промптом.
      3) Если NanoBanana недоступен / квота = 0 — отдаём заглушку с улучшенным промптом.
    """
    user = db.query(User).filter(User.chat_id == data.chat_id).first()
    if not user:
        user = User(chat_id=data.chat_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    # 1. декодируем картинку
    try:
        raw_image = base64.b64decode(data.image_b64)
    except Exception:
        return {"ok": False, "error": "bad_image_b64"}

    provider = OpenAIProvider()

    # 2. Улучшаем промпт через ChatGPT
    # improved_prompt = provider.improve_image_prompt(data.prompt)
    improved_prompt = data.prompt
    # 3. Пытаемся редактировать через NanoBanana
    b64 = provider.edit_image_b64(raw_image, improved_prompt, size=data.size or "768x768")

    if not b64:
        # NanoBanana сейчас недоступен (квоты нет, ошибка и т.п.)
        # Отвечаем заглушкой, но даём пользователю улучшенный промпт,
        # чтобы он видел, что именно будет отправляться, когда NanoBanana заработает.
        return {
            "ok": True,
            "stub": True,
            "caption": improved_prompt if improved_prompt else "🖼️ (симуляция) Изображение отредактировано.",
        }

    # 4. Успешная обработка
    return {
        "ok": True,
        "stub": False,
        "b64": b64,
        "caption": improved_prompt if improved_prompt else data.prompt.strip(),
    }
