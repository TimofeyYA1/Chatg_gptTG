# api_server/routers/payments.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits

router = APIRouter(prefix="/payments", tags=["payments"])

def _get_or_create_user(db: Session, chat_id: int) -> User:
    u = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
    if u:
        return u
    u = User(chat_id=chat_id, role="free", balance_cents=0)
    db.add(u); db.flush()
    db.add(PremiumCredits(user_id=u.id))
    db.commit(); db.refresh(u)
    return u

# --- Баланс ---
@router.get("/balance/{chat_id}")
def balance_get(chat_id: int, db: Session = Depends(get_db)):
    u = _get_or_create_user(db, chat_id)
    return {"balance_cents": u.balance_cents}

@router.post("/balance/topup")
def balance_topup(payload: dict, db: Session = Depends(get_db)):
    chat_id = int(payload["chat_id"]); amount = int(payload["amount"])
    if amount <= 0:
        raise HTTPException(400, "invalid amount")
    u = _get_or_create_user(db, chat_id)
    u.balance_cents += amount
    db.commit()
    return {"ok": True, "balance_cents": u.balance_cents}

# --- Докупки ---
# kind: messages|images|video
@router.post("/addons/buy")
def addons_buy(payload: dict, db: Session = Depends(get_db)):
    chat_id = int(payload["chat_id"])
    kind = str(payload["kind"])
    qty = int(payload["qty"])
    price_cents = int(payload["price_cents"])

    if kind not in {"messages", "images", "video"}:
        raise HTTPException(400, "invalid kind")
    if qty <= 0 or price_cents <= 0:
        raise HTTPException(400, "invalid qty/price")

    u = _get_or_create_user(db, chat_id)
    if u.balance_cents < price_cents:
        raise HTTPException(402, "insufficient balance")

    p = u.premium
    if not p:
        p = PremiumCredits(user_id=u.id)
        db.add(p); db.flush()

    # списываем
    u.balance_cents -= price_cents

    # прибавляем нужный кредит
    if kind == "messages":
        p.web_queries_left = (p.web_queries_left or 0) + qty
    elif kind == "images":
        p.image_credits = (p.image_credits or 0) + qty
    else:  # video
        p.video_seconds_left = (p.video_seconds_left or 0) + qty

    db.commit()
    db.refresh(u); db.refresh(p)

    return {
        "ok": True,
        "balance_cents": u.balance_cents,
        "addons": {
            "messages": p.web_queries_left or 0,
            "images": p.image_credits or 0,
            "video": p.video_seconds_left or 0,
        },
    }
