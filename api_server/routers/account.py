from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from db_adapter.database import get_db
from db_adapter.models import User, Subscription, PremiumCredits

router = APIRouter(tags=["account"])


# -------------------- helpers --------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_create_user(db: Session, chat_id: int) -> User:
    user = db.execute(
        select(User).where(User.chat_id == chat_id)
    ).scalar_one_or_none()
    if user:
        return user

    # дефолты для нового пользователя
    user = User(chat_id=chat_id, role="free", balance_cents=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _get_sub(db: Session, user_id: int) -> Optional[Subscription]:
    return db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    ).scalar_one_or_none()


def _get_or_create_credits(db: Session, user: User) -> PremiumCredits:
    """
    Гарантированно возвращает PremiumCredits для юзера.
    При создании нового — даем 1 бесплатную генерацию (image_credits=1).
    """
    p = user.premium
    if p:
        return p

    # --- ИЗМЕНЕНИЕ: Даем 1 бесплатную генерацию при создании ---
    p = PremiumCredits(user_id=user.id, image_credits=1)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# -------------------- routes --------------------

@router.get("/profile/{chat_id}")
def profile(chat_id: int, db: Session = Depends(get_db)):
    """
    Профиль пользователя + подписка + реальная статистика использования и лимитов.
    """
    user = _get_or_create_user(db, chat_id)
    sub = _get_sub(db, user.id)
    credits = _get_or_create_credits(db, user)

    # --- подписка ---
    role = "free"
    active_until_iso: str | None = None

    if sub and (sub.current_period_end is None or _now() < sub.current_period_end):
        role = sub.plan or "free"
        active_until_iso = (
            sub.current_period_end.isoformat()
            if sub.current_period_end
            else None
        )

    # --- usage из PremiumCredits ---
    usage = {
        "messages": credits.total_queries or 0,
        "images":   credits.web_queries or 0,
        "video":    credits.video_used or 0,
    }

    # --- лимиты / докупки ---
    premium_block = {
        "msg_limit_base":   credits.msg_limit_base or 0,
        "img_limit_base":   credits.img_limit_base or 0,
        "video_limit_base": credits.video_limit_base or 0,

        "web_queries_left":   credits.web_queries_left or 0,
        "image_credits":      credits.image_credits or 0,
        "video_seconds_left": credits.video_seconds_left or 0,
    }

    return {
        "chat_id": chat_id,
        "username": user.username,
        "balance_cents": user.balance_cents,
        "role": role,
        "active_until": active_until_iso,
        "usage": usage,
        "premium": premium_block,
    }