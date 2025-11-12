# api_server/routers/account.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from db_adapter.database import get_db
from db_adapter.models import User, Subscription

# Пытаемся импортировать PremiumCredits, но не падаем, если модели нет
try:
    from db_adapter.models import PremiumCredits  # type: ignore
except Exception:  # таблицы/модели может не быть
    PremiumCredits = None  # type: ignore[misc,assignment]

router = APIRouter()


# -------------------- helpers --------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_create_user(db: Session, chat_id: int) -> User:
    u = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
    if u:
        return u
    u = User(chat_id=chat_id)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _get_sub(db: Session, user_id: int) -> Optional[Subscription]:
    return db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    ).scalar_one_or_none()


def _get_premium(db: Session, user_id: int):
    """
    Безопасно возвращает объект PremiumCredits или None, если:
    - модели нет,
    - таблицы нет,
    - записи нет.
    """
    if PremiumCredits is None:
        return None
    try:
        return db.execute(
            select(PremiumCredits).where(PremiumCredits.user_id == user_id)  # type: ignore[attr-defined]
        ).scalar_one_or_none()
    except Exception:
        # на случай, если таблицы нет/миграции не применены
        return None


# -------------------- routes --------------------

@router.get("/profile/{chat_id}")
def profile(chat_id: int, db: Session = Depends(get_db)):
    user = _get_or_create_user(db, chat_id)
    sub = _get_sub(db, user.id)
    prem = _get_premium(db, user.id)

    # подписка: активна, если срок не истёк
    role = "free"
    active_until_iso = None
    if sub and (sub.current_period_end is None or _now() < sub.current_period_end):
        role = sub.plan or "free"
        active_until_iso = sub.current_period_end.isoformat() if sub.current_period_end else None

    # премиум-кредиты — безопасные дефолты
    premium_block = {
        "web_queries_left": getattr(prem, "web_queries_left", 0),
        "images_left": getattr(prem, "images_left", 0),
        "video_seconds_left": getattr(prem, "video_seconds_left", 0),
    }

    return {
        "chat_id": chat_id,
        "balance_cents": user.balance_cents,
        "role": role,
        "active_until": active_until_iso,
        "premium": premium_block,
    }
