from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import Dict, Any, Optional

from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits, CatalogItem, CatalogPage, CatalogCategory
from api_server.providers.openai_adapter import OpenAIProvider
import base64
import logging

logger = logging.getLogger("uvicorn.error")

router = APIRouter()

# --- CONSTANTS ---

PRESERVE_FACE_INSTRUCTION = (
    "CRITICAL REQUIREMENT: You MUST preserve the exact facial identity, structure, and features of the person from the source image. "
    "The output image must look exactly like the same person. "
    "Do not change the shape of the eyes, nose, mouth, or jawline. "
    "Keep the skin tone and texture consistent with the original. "
    "Apply the requested style (hair, clothes, background, artistic effect) AROUND the face, but keep the face recognizable. "
    "High fidelity face swap."
)

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
        # --- ИЗМЕНЕНИЕ: 1 бесплатная генерация для новых ---
        credits = PremiumCredits(user_id=user.id, web_queries=0, img_limit_base=0, image_credits=1)
        db.add(credits)
        db.commit()
        db.refresh(credits)

    # 1. Base limits
    base_used = credits.web_queries or 0
    base_limit = credits.img_limit_base or 0
    
    # 2. Addons (сюда попадает и бесплатная генерация)
    addons = credits.image_credits or 0
    
    if base_limit == 0 and addons == 0:
        return False
        
    # Списываем
    if base_used < base_limit:
        credits.web_queries = base_used + 1
    else:
        if addons > 0:
            credits.image_credits = addons - 1
        else:
            return False
            
    db.commit()
    return True

def _rollback_limit(db: Session, user: User):
    credits = db.query(PremiumCredits).filter(PremiumCredits.user_id == user.id).first()
    if not credits: return
    
    if credits.web_queries > 0:
        credits.web_queries -= 1
    else:
        credits.image_credits = (credits.image_credits or 0) + 1
    db.commit()

def _get_prompt_by_global_idx(db: Session, gender: str, cat_slug: str, global_idx: int) -> str | None:
    ITEMS_PER_PAGE = 9
    
    page_num = (global_idx - 1) // ITEMS_PER_PAGE + 1
    slot_num = (global_idx - 1) % ITEMS_PER_PAGE + 1

    logger.info(f"🔎 Поиск в БД: {cat_slug} #{global_idx} (pg {page_num}, slot {slot_num})")

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
    return db.execute(stmt).scalar_one_or_none()

# --- Routes ---

@router.get("/catalog/info")
def get_catalog_page_info(gender: str, cat: str, page: int, db: Session = Depends(get_db)):
    stmt = (
        select(func.count(CatalogItem.id))
        .join(CatalogPage, CatalogItem.page_id == CatalogPage.id)
        .join(CatalogCategory, CatalogPage.category_id == CatalogCategory.id)
        .where(
            CatalogCategory.slug == cat,
            CatalogCategory.gender == gender,
            CatalogPage.page_number == page
        )
    )
    count = db.execute(stmt).scalar() or 0
    return {"count": count}


@router.post("/generate_from_catalog")
def generate_from_catalog(data: CatalogGenIn, db: Session = Depends(get_db)):
    logger.info(f"🚀 Генерация из каталога для {data.chat_id}")

    user = db.query(User).filter(User.chat_id == data.chat_id).first()
    if not user:
        user = User(chat_id=data.chat_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    if not _check_and_increment_limit(db, user):
        return {"ok": False, "error": "limit_exceeded"}

    prompt_parts = []
    
    if data.shoot_sel and data.shoot_sel.get("cat") and data.shoot_sel.get("idx"):
        cat = data.shoot_sel["cat"]
        idx = int(data.shoot_sel["idx"])
        db_prompt = _get_prompt_by_global_idx(db, data.gender, cat, idx)
        if db_prompt:
            prompt_parts.append(f"{db_prompt}")
        else:
            _rollback_limit(db, user)
            return {"ok": False, "error": "preset_not_found"}

    elif data.editor_sel:
        base = "man" if data.gender == "m" else "woman"
        changes = []
        for cat, idx in data.editor_sel.items():
            if not idx: continue
            p = _get_prompt_by_global_idx(db, data.gender, cat, int(idx))
            if p: changes.append(p)
        
        if not changes:
            _rollback_limit(db, user)
            return {"ok": False, "error": "no_selection"}
            
        combined_features = ", ".join(changes)
        prompt_parts.append(f"A photorealistic portrait of a {base} with {combined_features}")
    
    else:
        _rollback_limit(db, user)
        return {"ok": False, "error": "no_selection"}

    prompt_parts.append(PRESERVE_FACE_INSTRUCTION)
    final_prompt = ". ".join(prompt_parts)
    logger.info(f"📝 Итоговый промпт: {final_prompt[:200]}...")

    try:
        raw_image = base64.b64decode(data.image_b64)
    except Exception:
        _rollback_limit(db, user)
        return {"ok": False, "error": "bad_image_b64"}

    provider = OpenAIProvider()
    b64 = provider.edit_image_b64(raw_image, final_prompt, size="768x768")

    if not b64:
        _rollback_limit(db, user)
        return {"ok": True, "stub": True, "caption": "⚠️ Не удалось сгенерировать изображение."}

    return {"ok": True, "stub": False, "b64": b64, "caption": "✨ Готово!"}


@router.post("/edit")
def edit_image(data: ImageEditIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.chat_id == data.chat_id).first()
    if not user:
        user = User(chat_id=data.chat_id)
        db.add(user); db.commit()

    if not _check_and_increment_limit(db, user):
        return {"ok": False, "error": "limit_exceeded"}

    try:
        raw_image = base64.b64decode(data.image_b64)
    except Exception:
        _rollback_limit(db, user)
        return {"ok": False, "error": "bad_image_b64"}

    provider = OpenAIProvider()
    full_prompt = f"{data.prompt}. {PRESERVE_FACE_INSTRUCTION}"
    logger.info(f"📝 Custom Edit Prompt: {full_prompt[:100]}...")

    b64 = provider.edit_image_b64(raw_image, full_prompt, size=data.size or "768x768")

    if not b64:
        _rollback_limit(db, user)
        return {"ok": True, "stub": True, "caption": "⚠️ Генерация не удалась."}

    return {"ok": True, "stub": False, "b64": b64, "caption": "✨ Готово!"}