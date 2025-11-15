from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits

router = APIRouter( tags=["usage"])


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

    # создаём пустые кредиты сразу (но только один раз)
    credits = PremiumCredits(user_id=user.id)
    db.add(credits)
    db.commit()

    return user


def _get_or_create_credits(db: Session, user: User) -> PremiumCredits:
    credits = db.execute(
        select(PremiumCredits).where(PremiumCredits.user_id == user.id)
    ).scalar_one_or_none()

    if credits:
        return credits

    credits = PremiumCredits(user_id=user.id)
    db.add(credits)
    db.commit()
    db.refresh(credits)
    return credits


@router.post("/increment")
def increment(payload: dict, db: Session = Depends(get_db)):
    """
    payload: { chat_id: int, kind: "messages"|"images"|"video", value?: int }

    messages -> total_queries
    images   -> web_queries
    video    -> video_used
    """
    try:
        chat_id = int(payload.get("chat_id"))
        kind = str(payload.get("kind"))
        value = int(payload.get("value", 1))
    except Exception:
        raise HTTPException(400, "invalid payload")

    if value <= 0:
        raise HTTPException(400, "value must be positive")
    if kind not in {"messages", "images", "video"}:
        raise HTTPException(400, "invalid kind")

    user = _get_or_create_user(db, chat_id)
    credits = _get_or_create_credits(db, user)

    if kind == "messages":
        credits.total_queries = (credits.total_queries or 0) + value
    elif kind == "images":
        credits.web_queries = (credits.web_queries or 0) + value
    elif kind == "video":
        credits.video_used = (credits.video_used or 0) + value

    db.commit()
    return {"ok": True}
