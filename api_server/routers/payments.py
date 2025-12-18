from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits, Subscription
from datetime import datetime, timezone

router = APIRouter(tags=["payments"])

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _get_or_create_user(db: Session, chat_id: int) -> User:
    user = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
    if user: return user
    user = User(chat_id=chat_id, role="free", balance_cents=0)
    db.add(user); db.commit(); db.refresh(user)
    return user

def _get_or_create_credits(db: Session, user_id: int) -> PremiumCredits:
    c = db.execute(select(PremiumCredits).where(PremiumCredits.user_id == user_id)).scalar_one_or_none()
    if c: return c
    c = PremiumCredits(user_id=user_id)
    db.add(c); db.commit(); db.refresh(c)
    return c

@router.post("/balance/topup")
def balance_topup(payload: dict, db: Session = Depends(get_db)):
    chat_id = int(payload["chat_id"])
    amount = int(payload["amount"])
    u = _get_or_create_user(db, chat_id)
    u.balance_cents += amount
    db.commit()
    return {"ok": True}

@router.post("/addons/buy")
def addons_buy(payload: dict, db: Session = Depends(get_db)):
    """
    Покупка пакета.
    payload: { chat_id, qty, price_cents }
    """
    chat_id = int(payload["chat_id"])
    qty = int(payload["qty"])
    price_cents = int(payload["price_cents"])

    user = _get_or_create_user(db, chat_id)
    
    # Проверка: есть ли активная подписка? (Без подписки пакеты не работают/не покупаются по условию)
    sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
    if not sub or not sub.current_period_end or sub.current_period_end < _now():
        raise HTTPException(400, "subscription_required")

    if user.balance_cents < price_cents:
        raise HTTPException(402, "insufficient funds")

    credits = _get_or_create_credits(db, user.id)

    # Списываем
    user.balance_cents -= price_cents
    # Начисляем
    credits.image_credits = (credits.image_credits or 0) + qty

    db.commit()
    return {"ok": True, "added": qty}