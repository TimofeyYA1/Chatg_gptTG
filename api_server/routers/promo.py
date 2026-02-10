from __future__ import annotations
import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from db_adapter.database import get_db
from db_adapter.models import User, PromoToken, PremiumCredits, Subscription

router = APIRouter(tags=["promo"])

class GeneratePromoIn(BaseModel):
    count: int = 1
    credits: int = 10

class UsePromoIn(BaseModel):
    chat_id: int
    token: str

def _get_or_create_user(db: Session, chat_id: int) -> User:
    u = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
    if u: return u
    u = User(chat_id=chat_id, role="free", balance_cents=0)
    db.add(u); db.commit(); db.refresh(u)
    return u

def _get_or_create_credits(db: Session, user_id: int) -> PremiumCredits:
    p = db.execute(select(PremiumCredits).where(PremiumCredits.user_id == user_id)).scalar_one_or_none()
    if p: return p
    p = PremiumCredits(user_id=user_id)
    db.add(p); db.commit(); db.refresh(p)
    return p

@router.post("/generate")
def generate_promo(payload: GeneratePromoIn, db: Session = Depends(get_db)):
    tokens = []
    for _ in range(payload.count):
        # Generate a nice looking token or just random
        token_str = secrets.token_urlsafe(12)
        token = PromoToken(token=token_str, credits=payload.credits)
        db.add(token)
        tokens.append(token_str)
    db.commit()
    return {"ok": True, "tokens": tokens}

@router.post("/use")
def use_promo(payload: UsePromoIn, db: Session = Depends(get_db)):
    # 1. Находим токен
    token = db.execute(select(PromoToken).where(PromoToken.token == payload.token)).scalar_one_or_none()
    if not token:
        raise HTTPException(404, "token_not_found")
    if token.is_used:
        raise HTTPException(400, "token_already_used")
    
    # 2. Находим или создаем пользователя
    user = _get_or_create_user(db, payload.chat_id)
    
    # 3. Проверяем, не было ли подписки
    # Условие: "для тех, кто не покупал подписку"
    sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
    if sub:
        raise HTTPException(400, "already_had_subscription")
    
    # 4. Проверяем, не использовал ли этот пользователь УЖЕ какой-либо промокод
    # "срабатывает только 1 раз"
    already_used = db.execute(select(PromoToken).where(PromoToken.used_by_id == user.id)).scalar_one_or_none()
    if already_used:
        raise HTTPException(400, "promo_already_used_by_user")

    # 5. Начисляем кредиты
    credits = _get_or_create_credits(db, user.id)
    credits.image_credits = (credits.image_credits or 0) + token.credits
    
    # 6. Помечаем как использованный
    token.is_used = True
    token.used_by_id = user.id
    db.commit()
    
    return {"ok": True, "credits_added": token.credits}
