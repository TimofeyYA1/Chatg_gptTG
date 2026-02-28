from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import Dict, Any, Optional, List

from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits, Subscription, CatalogItem, CatalogPage, CatalogCategory
from api_server.providers.openai_adapter import OpenAIProvider
from common.config import settings
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
    "High fidelity face swap."
)

PRESERVE_BACKGROUND_INSTRUCTION = (
    "CRITICAL ENV REQUIREMENT: Keep the original background, environment, lighting, clothing, and pose EXACTLY as they are in the source image. "
    "Do NOT regenerate the background. Do NOT change the location. "
    "Only apply the specific requested changes (hair, glasses, makeup, etc) to the subject. "
    "Seamlessly blend the changes into the original image."
)

# --- Pydantic Models ---

class ImageIn(BaseModel):
    chat_id: int
    prompt: str
    size: str | None = "1536x1536"

class ImageEditIn(BaseModel):
    chat_id: int
    prompt: str
    image_b64: str
    size: str | None = "1536x1536"

class CatalogGenIn(BaseModel):
    chat_id: int
    image_b64: str
    gender: str  # 'm' or 'f'
    editor_sel: Dict[str, int] = {} 
    shoot_sel: Dict[str, Any] = {} 

class TitlesIn(BaseModel):
    gender: str
    selections: Dict[str, int]

# --- Helpers ---

def _check_and_increment_limit(db: Session, user: User) -> bool:
    credits = db.query(PremiumCredits).filter(PremiumCredits.user_id == user.id).first()
    if not credits:
        credits = PremiumCredits(user_id=user.id, web_queries=0, img_limit_base=0, image_credits=1)
        db.add(credits)
        db.commit()
        db.refresh(credits)

    used = credits.web_queries or 0
    limit = credits.img_limit_base or 0
    addons = credits.image_credits or 0
    
    if limit == 0 and addons == 0:
        return False
        
    if used < limit:
        credits.web_queries = used + 1
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

def _get_user_model_tier(db: Session, user_id: int) -> str:
    """Определяет tier модели для NanoBanana: start / pro / elite."""
    sub = db.execute(select(Subscription).where(Subscription.user_id == user_id)).scalar_one_or_none()
    if not sub or not sub.plan:
        return "start"

    plan = sub.plan.lower()
    if "std2" in plan:
        return "pro"
    if "_pro" in plan:
        return "elite"
    if "_std" in plan:
        return "start"
    return "start"

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


@router.post("/catalog/titles")
def get_catalog_titles(data: TitlesIn, db: Session = Depends(get_db)):
    result = {}
    ITEMS_PER_PAGE = 9

    for cat_slug, global_idx in data.selections.items():
        page_num = (global_idx - 1) // ITEMS_PER_PAGE + 1
        slot_num = (global_idx - 1) % ITEMS_PER_PAGE + 1
        
        stmt = (
            select(CatalogItem.title)
            .join(CatalogPage, CatalogItem.page_id == CatalogPage.id)
            .join(CatalogCategory, CatalogPage.category_id == CatalogCategory.id)
            .where(
                CatalogCategory.slug == cat_slug,
                CatalogCategory.gender == data.gender,
                CatalogPage.page_number == page_num,
                CatalogItem.slot_number == slot_num
            )
        )
        title = db.execute(stmt).scalar_one_or_none()
        if title:
            result[cat_slug] = title
        else:
            result[cat_slug] = f"#{global_idx}"
            
    return result


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

    # Определяем tier модели (start/pro/elite)
    model_tier = _get_user_model_tier(db, user.id)

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
        prompt_parts.append(f"Modify the {base} in this image: add {combined_features}")
        prompt_parts.append(PRESERVE_BACKGROUND_INSTRUCTION)
    
    else:
        _rollback_limit(db, user)
        return {"ok": False, "error": "no_selection"}

    # prompt_parts.append(PRESERVE_FACE_INSTRUCTION) # Переносим в системные инструкции провайдера
    final_prompt = ". ".join(prompt_parts)
    logger.info(f"📝 Итоговый промпт: {final_prompt[:200]}...")

    try:
        raw_image = base64.b64decode(data.image_b64)
    except Exception:
        _rollback_limit(db, user)
        return {"ok": False, "error": "bad_image_b64"}

    provider = OpenAIProvider()
    # Передаем вычисленный tier модели
    logger.info(f"🎨 Starting generation for user {data.chat_id} (tier: {model_tier})")
    result = provider.edit_image_b64(raw_image, final_prompt, size="1536x1536", model_tier=model_tier)
    
    b64 = result.get("b64")
    image_ext = str(result.get("image_ext") or "jpg").lower()
    if image_ext == "jpeg":
        image_ext = "jpg"
    if image_ext not in {"jpg", "png", "webp"}:
        image_ext = "jpg"
    fail_reason = result.get("reason", "unknown")

    if not b64:
        _rollback_limit(db, user)
        
        # Определяем текст ошибки для пользователя
        if fail_reason == "server_overloaded" or fail_reason == "timeout":
            caption_text = "⚡️ Сейчас модель временно перегружена.\nПожалуйста, попробуйте повторить генерацию немного позже."
        elif fail_reason == "safety_filter":
            caption_text = "⚠️ Отредактируйте промпт: он не прошел фильтр безопасности."
        else:
            caption_text = "⚠️ Не удалось сгенерировать изображение."

        logger.warning(f"❌ Generation from catalog failed for user {data.chat_id} | Reason: {fail_reason} | Prompt: {final_prompt}")
        return {
            "ok": True, 
            "stub": True, 
            "caption": caption_text,
            "fail_reason": fail_reason
        }

    return {"ok": True, "stub": False, "b64": b64, "caption": "✨ Готово!", "image_ext": image_ext}


@router.post("/edit")
def edit_image(data: ImageEditIn, db: Session = Depends(get_db)):
    """
    Редактирование по СВОЕМУ промпту.
    """
    user = db.query(User).filter(User.chat_id == data.chat_id).first()
    if not user:
        user = User(chat_id=data.chat_id)
        db.add(user); db.commit()

    if not _check_and_increment_limit(db, user):
        return {"ok": False, "error": "limit_exceeded"}
    
    # Определяем tier модели (start/pro/elite)
    model_tier = _get_user_model_tier(db, user.id)

    try:
        raw_image = base64.b64decode(data.image_b64)
    except Exception:
        _rollback_limit(db, user)
        return {"ok": False, "error": "bad_image_b64"}

    provider = OpenAIProvider()
    
    # --- 1. СТРОГИЙ ПЕРЕВОД ПРОМПТА НА АНГЛИЙСКИЙ ---
    # Используем chat_reply для перевода БЕЗ "улучшений" и отсебятины.
    
    raw_prompt = data.prompt.strip()
    
    # Системный промпт для строгого переводчика
    translator_system = (
        "You are a professional translator. Translate the user's text to English accurately and strictly. "
        "Do NOT add any extra descriptions, style improvements, or conversational filler. "
        "Do NOT change the meaning. Keep technical terms (like '16:9', '4k', 'vertical') as is. "
        "Output ONLY the translation."
    )
    
    try:
        # Используем gemini-2.5-pro для перевода
        translated_prompt = provider.nano_chat_reply(
            system_prompt=translator_system, 
            user_prompt=raw_prompt,
            model_name=settings.NANOBANANA_MODEL_CHAT
        )
        if not translated_prompt or "Error" in translated_prompt:
            translated_prompt = raw_prompt
    except Exception as e:
        logger.warning(f"⚠️ Prompt translation failed: {e}")
        translated_prompt = raw_prompt

    logger.info(f"📝 Original: {raw_prompt}")
    logger.info(f"🇬🇧 Translated: {translated_prompt}")

    # Передаем вычисленный tier модели и переведенный промпт
    logger.info(f"🎨 Starting custom edit for user {data.chat_id} (tier: {model_tier})")
    result = provider.edit_image_b64(raw_image, translated_prompt, size=data.size or "1536x1536", model_tier=model_tier)
    
    b64_str = result.get("b64")
    image_ext = str(result.get("image_ext") or "jpg").lower()
    if image_ext == "jpeg":
        image_ext = "jpg"
    if image_ext not in {"jpg", "png", "webp"}:
        image_ext = "jpg"
    fail_reason = result.get("reason", "unknown")

    if not b64_str:
        _rollback_limit(db, user)

        # Определяем текст ошибки для пользователя
        if fail_reason == "server_overloaded" or fail_reason == "timeout":
            caption_text = "⚡️ Сейчас модель временно перегружена.\nПожалуйста, попробуйте повторить генерацию немного позже."
        elif fail_reason == "safety_filter":
            caption_text = "⚠️ Отредактируйте промпт: он не прошел фильтр безопасности."
        else:
            caption_text = "⚠️ Не удалось сгенерировать изображение."

        logger.warning(f"❌ Generation failed for user {data.chat_id} | Reason: {fail_reason} | Prompt: {data.prompt}")
        return {
            "ok": True, 
            "stub": True, 
            "caption": caption_text,
            "fail_reason": fail_reason 
        }

    return {"ok": True, "stub": False, "b64": b64_str, "caption": "✨ Готово!", "image_ext": image_ext}

