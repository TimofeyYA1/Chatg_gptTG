from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits

router = APIRouter(tags=["usage"])


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


def _get_or_create_credits(db: Session, user: User) -> PremiumCredits:
    # если есть — берём
    credits = db.execute(
        select(PremiumCredits).where(PremiumCredits.user_id == user.id)
    ).scalar_one_or_none()
    if credits:
        return credits

    # если нет — создаём один раз
    credits = PremiumCredits(user_id=user.id)
    db.add(credits)
    db.commit()
    db.refresh(credits)
    return credits


def _apply_limit(kind: str, value: int, p: PremiumCredits) -> None:
    """
    messages:
        базовый: msg_limit_base
        usage: total_queries
        докупки: web_queries_left

    images:
        базовый: img_limit_base
        usage: web_queries
        докупки: image_credits

    video:
        базовый: video_limit_base
        usage: video_used
        докупки: video_seconds_left

    Алгоритм для всех одинаковый:
        1) считаем остаток по базовому лимиту (base - used)
        2) смотрим, хватает ли base + addons на value
        3) если нет — 402
        4) если да — увеличиваем used, и если ушли «поверх» base, то режем докупки
    """

    if kind == "messages":
        base = p.msg_limit_base or 0
        used = p.total_queries or 0
        addon = p.web_queries_left or 0

        remaining_plan = max(0, base - used)
        total_remaining = remaining_plan + addon
        if value > total_remaining:
            raise HTTPException(402, "text limit exceeded")

        used_before = used
        used_after = used + value

        over_before = max(0, used_before - base)
        over_after = max(0, used_after - base)
        delta_over = max(0, over_after - over_before)

        p.total_queries = used_after
        p.web_queries_left = max(0, addon - delta_over)

    elif kind == "images":
        base = p.img_limit_base or 0
        used = p.web_queries or 0
        addon = p.image_credits or 0

        remaining_plan = max(0, base - used)
        total_remaining = remaining_plan + addon
        if value > total_remaining:
            raise HTTPException(402, "image limit exceeded")

        used_before = used
        used_after = used + value

        over_before = max(0, used_before - base)
        over_after = max(0, used_after - base)
        delta_over = max(0, over_after - over_before)

        p.web_queries = used_after
        p.image_credits = max(0, addon - delta_over)

    elif kind == "video":
        base = p.video_limit_base or 0
        used = p.video_used or 0
        addon = p.video_seconds_left or 0

        remaining_plan = max(0, base - used)
        total_remaining = remaining_plan + addon
        if value > total_remaining:
            raise HTTPException(402, "video limit exceeded")

        used_before = used
        used_after = used + value

        over_before = max(0, used_before - base)
        over_after = max(0, used_after - base)
        delta_over = max(0, over_after - over_before)

        p.video_used = used_after
        p.video_seconds_left = max(0, addon - delta_over)

    else:
        raise HTTPException(400, "invalid kind")


@router.post("/increment")
def increment_usage(payload: dict, db: Session = Depends(get_db)):
    """
    payload: { chat_id: int, kind: "messages"|"images"|"video", value?: int }

    - создаём user/credits при первом запросе
    - проверяем лимит; если не хватает -> 402
    - если хватает -> обновляем usage / докупки и 200
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

    _apply_limit(kind, value, credits)

    db.commit()
    return {"ok": True}
