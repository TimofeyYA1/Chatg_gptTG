from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits
from pydantic import BaseModel


class BalanceTopupIn(BaseModel):
    chat_id: int
    amount: int


router = APIRouter(tags=["payments"])


def _get_or_create_user(db: Session, chat_id: int) -> User:
    user = db.execute(
        select(User).where(User.chat_id == chat_id)
    ).scalar_one_or_none()

    if user:
        return user

    user = User(chat_id=chat_id, role="free", balance_cents=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _get_or_create_credits(db: Session, user_id: int) -> PremiumCredits:
    """
    Гарантируем, что на пользователя есть одна строка в premium_credits.
    """
    credits = db.execute(
        select(PremiumCredits).where(PremiumCredits.user_id == user_id)
    ).scalar_one_or_none()
    if credits:
        return credits

    credits = PremiumCredits(user_id=user_id)
    db.add(credits)
    db.commit()
    db.refresh(credits)
    return credits


# --- Баланс ---


@router.get("/balance/{chat_id}")
def balance_get(chat_id: int, db: Session = Depends(get_db)):
    u = _get_or_create_user(db, chat_id)
    return {"balance_cents": u.balance_cents}


@router.post("/balance/topup")
def balance_topup(payload: dict, db: Session = Depends(get_db)):
    chat_id = int(payload["chat_id"])
    amount = int(payload["amount"])
    if amount <= 0:
        raise HTTPException(400, "invalid amount")
    u = _get_or_create_user(db, chat_id)
    u.balance_cents += amount
    db.commit()
    return {"ok": True, "balance_cents": u.balance_cents}


# --- Докупки ---


@router.post("/addons/buy")
def addons_buy(payload: dict, db: Session = Depends(get_db)):
    """
    payload: { chat_id: int, kind: "messages"|"images"|"video", qty: int, price_cents: int }
    """
    try:
        chat_id = int(payload["chat_id"])
        kind = str(payload["kind"])
        qty = int(payload["qty"])
        price_cents = int(payload["price_cents"])
    except Exception:
        raise HTTPException(400, "invalid payload")

    if kind not in {"messages", "images", "video"}:
        raise HTTPException(400, "invalid kind")
    if qty <= 0 or price_cents <= 0:
        raise HTTPException(400, "invalid qty/price")

    user = _get_or_create_user(db, chat_id)
    if user.balance_cents < price_cents:
        # бот по статус-коду 402 показывает "Недостаточно средств"
        raise HTTPException(402, "insufficient balance")

    credits = _get_or_create_credits(db, user.id)

    # списываем деньги
    user.balance_cents -= price_cents

    # докидываем нужный кредит
    if kind == "messages":
        credits.web_queries_left = (credits.web_queries_left or 0) + qty
    elif kind == "images":
        credits.image_credits = (credits.image_credits or 0) + qty
    else:  # video
        credits.video_seconds_left = (credits.video_seconds_left or 0) + qty

    db.commit()
    db.refresh(user)
    db.refresh(credits)

    return {
        "ok": True,
        "balance_cents": user.balance_cents,
        "addons": {
            "messages": credits.web_queries_left or 0,
            "images": credits.image_credits or 0,
            "video": credits.video_seconds_left or 0,
        },
    }
