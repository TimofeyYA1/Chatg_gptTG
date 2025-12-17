from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import Dict, Any, Optional

from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits, CatalogItem, CatalogPage, CatalogCategory
from api_server.providers.openai_adapter import OpenAIProvider
import base64

# --- ЛОГИРОВАНИЕ ---
import logging
logger = logging.getLogger("uvicorn.error")

router = APIRouter()

# --- Pydantic Models ---

class ImageIn(BaseModel):
    chat_id: int
    prompt: str
    size: str | None = "768x768"

class ImageEditIn(BaseModel):
    chat_id: int
    prompt: str
    image_b64: str
    size: str | None = "768x768"

class CatalogGenIn(BaseModel):
    chat_id: int
    image_b64: str
    gender: str  # 'm' or 'f'
    editor_sel: Dict[str, int] = {} 
    shoot_sel: Dict[str, Any] = {} 

# --- Helpers ---

def _check_and_increment_limit(db: Session, user: User) -> bool:
    credits = db.query(PremiumCredits).filter(PremiumCredits.user_id == user.id).first()
    if not credits:
        credits = PremiumCredits(user_id=user.id, web_queries=0, img_limit_base=0)
        db.add(credits)
        db.commit()
        db.refresh(credits)

    used = credits.web_queries or 0
    limit = credits.img_limit_base or 0
    
    # Если лимит > 0, проверяем. Если 0 (бесплатно), не пускаем (или пускаем, если это админ)
    # Тут строгая логика: если лимит 0 и использовано 0 — это конец.
    if limit > 0 and used >= limit:
        return False
    
    # Инкремент
    credits.web_queries = used + 1
    db.commit()
    return True

def _get_prompt_by_global_idx(db: Session, gender: str, cat_slug: str, global_idx: int) -> str | None:
    """
    Превращает глобальный индекс (1..N) в запись из БД.
    """
    ITEMS_PER_PAGE = 9
    
    page_num = (global_idx - 1) // ITEMS_PER_PAGE + 1
    slot_num = (global_idx - 1) % ITEMS_PER_PAGE + 1

    logger.info(f"🔍 Поиск в БД: Категория='{cat_slug}', Пол='{gender}', Стр={page_num}, Слот={slot_num}")

    # Ищем категорию
    stmt = (
        select(CatalogItem.prompt)
        .join(CatalogPage, CatalogItem.page_id == CatalogPage.id)
        .join(CatalogCategory, CatalogPage.category_id == CatalogCategory.id)
        .where(
            CatalogCategory.slug == cat_slug,
            CatalogCategory.gender == gender,
            CatalogPage.page_number == page_num,
            CatalogItem.slot_number == slot_num
        )
    )
    result = db.execute(stmt).scalar_one_or_none()
    
    if result:
        logger.info(f"✅ Промпт найден: {result[:50]}...")
    else:
        logger.warning(f"❌ Промпт НЕ найден! Проверьте catalog_data.json и sync_catalog.py")
        
    return result

# --- Routes ---

@router.post("/generate_from_catalog")
def generate_from_catalog(data: CatalogGenIn, db: Session = Depends(get_db)):
    """
    Генерация на основе выбора в каталоге (Editor или Shoot).
    """
    logger.info(f"🚀 Новый запрос генерации: chat_id={data.chat_id}, gender={data.gender}")
    logger.info(f"📥 Выбор: Shoot={data.shoot_sel}, Editor={data.editor_sel}")

    # 1. User check
    user = db.query(User).filter(User.chat_id == data.chat_id).first()
    if not user:
        user = User(chat_id=data.chat_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    # 2. Limits check
    if not _check_and_increment_limit(db, user):
        logger.warning(f"⛔ Лимит исчерпан для {data.chat_id}")
        return {"ok": False, "error": "limit_exceeded"}

    # 3. Build Prompt
    final_prompt = ""
    
    # А) ФОТОСЕССИЯ
    if data.shoot_sel and data.shoot_sel.get("cat") and data.shoot_sel.get("idx"):
        cat = data.shoot_sel["cat"]
        idx = int(data.shoot_sel["idx"])
        prompt = _get_prompt_by_global_idx(db, data.gender, cat, idx)
        
        if prompt:
            final_prompt = f"professional photo, {prompt}, preserve facial features, high quality, 8k"
        else:
            logger.error("❌ Ошибка: не удалось найти промпт для фотосессии")
            return {"ok": False, "error": "preset_not_found"}

    # Б) РЕДАКТОР
    elif data.editor_sel:
        prompts_list = []
        base = "man" if data.gender == "m" else "woman"
        prompts_list.append(f"portrait of a {base}")
        
        for cat, idx in data.editor_sel.items():
            if not idx: continue
            p = _get_prompt_by_global_idx(db, data.gender, cat, int(idx))
            if p:
                prompts_list.append(p)
        
        if len(prompts_list) == 1:
            return {"ok": False, "error": "no_selection"}
            
        prompts_list.append("realistic, 8k, high detailed, preserve facial features")
        final_prompt = ", ".join(prompts_list)
    
    else:
        logger.error("❌ Ошибка: пустой выбор (нет ни editor, ни shoot)")
        return {"ok": False, "error": "no_selection"}

    logger.info(f"🎨 Итоговый промпт: {final_prompt}")

    # 4. Generate
    try:
        raw_image = base64.b64decode(data.image_b64)
    except Exception:
        return {"ok": False, "error": "bad_image_b64"}

    provider = OpenAIProvider()
    
    # --- ВАЖНО: Если у тебя нет рабочего API ключа, provider вернет оригинал ---
    logger.info("📡 Отправка запроса в нейросеть (OpenAIProvider)...")
    b64 = provider.edit_image_b64(raw_image, final_prompt, size="768x768")

    if not b64:
        logger.warning("⚠️ Нейросеть вернула пустой результат (или заглушку)")
        return {
            "ok": True,
            "stub": True,
            "caption": final_prompt
        }

    # Проверка: если вернулось то же самое фото (сравнение по длине байтов грубо, но эффективно)
    if len(b64) == len(data.image_b64):
        logger.warning("⚠️ Внимание! OpenAIProvider вернул исходное изображение. Проверь API Key или реализацию адаптера.")

    return {
        "ok": True,
        "stub": False,
        "b64": b64,
        "caption": "✨ Готово!"
    }


@router.post("/generate")
def generate_image(data: ImageIn, db: Session = Depends(get_db)):
    pass 

@router.post("/edit")
def edit_image(data: ImageEditIn, db: Session = Depends(get_db)):
    # ... (аналогично с проверкой лимитов)
    user = db.query(User).filter(User.chat_id == data.chat_id).first()
    if not _check_and_increment_limit(db, user):
        return {"ok": False, "error": "limit_exceeded"}

    try:
        raw_image = base64.b64decode(data.image_b64)
    except Exception:
        return {"ok": False, "error": "bad_image_b64"}

    provider = OpenAIProvider()
    b64 = provider.edit_image_b64(raw_image, data.prompt, size=data.size or "768x768")

    if not b64:
        return {"ok": True, "stub": True, "caption": data.prompt}

    return {"ok": True, "stub": False, "b64": b64, "caption": data.prompt}