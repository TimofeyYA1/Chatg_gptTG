# api_server/routers/referrals.py
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from db_adapter.database import get_db
from db_adapter.models import User, Referral
from common.config import settings

router = APIRouter(prefix="/referrals", tags=["referrals"])


def _get_user(db: Session, chat_id: int) -> User | None:
    return db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()


@router.get("/summary/{chat_id}")
def referrals_summary(chat_id: int, db: Session = Depends(get_db)):
    user = _get_user(db, chat_id)
    if not user:
        # если юзера ещё нет в БД — просто нули и ссылка
        link = f"https://t.me/{getattr(settings, 'BOT_NAME', 'ai_superbot')}?start={chat_id}"
        return {"invited": 0, "subscribed": 0, "ref_link": link}

    invited = db.execute(
        select(func.count(Referral.id)).where(Referral.referrer_id == user.id)
    ).scalar() or 0

    subscribed = db.execute(
        select(func.count(Referral.id)).where(
            Referral.referrer_id == user.id, Referral.bonus_awarded.is_(True)
        )
    ).scalar() or 0

    link = f"https://t.me/{getattr(settings, 'BOT_NAME', 'ai_superbot')}?start={chat_id}"
    return {"invited": invited, "subscribed": subscribed, "ref_link": link}
