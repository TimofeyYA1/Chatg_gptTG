from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api_server.services.cloudpayments import cp_service
from common.subscriptions import (
    get_plan_spec,
    normalize_plan_key,
    plan_duration_end,
    plan_images_limit,
    plan_price_cents,
    plan_price_rub,
)
from db_adapter.database import get_db
from db_adapter.models import PremiumCredits, Subscription, User

router = APIRouter(tags=["subscriptions"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_create_user(db: Session, chat_id: int) -> User:
    user = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
    if user:
        return user
    user = User(chat_id=chat_id, role="free", balance_cents=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _get_sub(db: Session, user_id: int) -> Subscription | None:
    return db.execute(select(Subscription).where(Subscription.user_id == user_id)).scalar_one_or_none()


def _get_or_create_credits(db: Session, user_id: int) -> PremiumCredits:
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


class SetPlanIn(BaseModel):
    chat_id: int
    plan: str
    price_cents: int | None = None


class AdminGiveIn(BaseModel):
    chat_id: int
    days: int
    generations: int


@router.get("/summary/{chat_id}")
def summary(chat_id: int, db: Session = Depends(get_db)):
    user = _get_or_create_user(db, chat_id)
    sub = _get_sub(db, user.id)
    credits = _get_or_create_credits(db, user.id)

    if sub and sub.current_period_end and _now() >= sub.current_period_end:
        credits.msg_limit_base = 0
        credits.img_limit_base = 0
        credits.video_limit_base = 0
        credits.image_credits = 0
        db.delete(sub)
        db.commit()
        sub = None

    if not sub:
        role = "free"
        active_until = None
        auto_renew = False
        renew_price = 0
    else:
        role = sub.plan or "free"
        active_until = sub.current_period_end
        auto_renew = not bool(sub.cancel_at_period_end)
        renew_price = plan_price_rub(role)

    limits = {
        "messages": credits.msg_limit_base or 0,
        "images": credits.img_limit_base or 0,
        "video": credits.video_limit_base or 0,
    }
    usage = {
        "messages": credits.total_queries or 0,
        "images": credits.web_queries or 0,
        "video": credits.video_used or 0,
    }
    addons = {
        "messages": credits.web_queries_left or 0,
        "images": credits.image_credits or 0,
        "video": credits.video_seconds_left or 0,
    }
    totals = {
        "messages": limits["messages"] + addons["messages"],
        "images": limits["images"] + addons["images"],
        "video": limits["video"] + addons["video"],
    }

    return {
        "role": role,
        "balance_cents": user.balance_cents,
        "active_until": active_until.isoformat() if active_until else None,
        "auto_renew": auto_renew,
        "renew_price": renew_price,
        "limits": limits,
        "usage": usage,
        "addons": addons,
        "totals": totals,
    }


@router.post("/set_plan")
def set_plan(payload: SetPlanIn, db: Session = Depends(get_db)):
    plan = normalize_plan_key(payload.plan)
    if not plan or not get_plan_spec(plan):
        raise HTTPException(400, "unknown plan")

    expected_cents = plan_price_cents(plan)
    if payload.price_cents is not None and payload.price_cents != expected_cents:
        raise HTTPException(400, "price mismatch")

    user = _get_or_create_user(db, payload.chat_id)
    if (user.balance_cents or 0) < expected_cents:
        raise HTTPException(402, "insufficient funds")
    user.balance_cents -= expected_cents

    sub = _get_sub(db, user.id)
    start = _now()
    if sub and sub.current_period_end and sub.current_period_end > start:
        start = sub.current_period_end
    end = plan_duration_end(start, plan)

    if not sub:
        sub = Subscription(
            user_id=user.id,
            plan=plan,
            status="active",
            current_period_end=end,
            cancel_at_period_end=False,
        )
        db.add(sub)
    else:
        sub.plan = plan
        sub.status = "active"
        sub.current_period_end = end
        sub.cancel_at_period_end = False

    credits = _get_or_create_credits(db, user.id)
    credits.msg_limit_base = 0
    credits.img_limit_base = plan_images_limit(plan)
    credits.video_limit_base = 0
    credits.web_queries = 0

    db.commit()
    return {"ok": True, "plan": plan}


@router.post("/cancel")
async def cancel(payload: dict, db: Session = Depends(get_db)):
    try:
        chat_id = int(payload["chat_id"])
    except Exception as exc:
        raise HTTPException(400, "invalid payload") from exc

    user = _get_or_create_user(db, chat_id)
    sub = _get_sub(db, user.id)
    if not sub:
        raise HTTPException(400, "no sub")

    if sub.cp_sub_id:
        await cp_service.cancel_subscription(sub.cp_sub_id)
        sub.cp_sub_id = None

    sub.cancel_at_period_end = True
    db.commit()
    return {"ok": True}


@router.post("/resume")
async def resume(payload: dict, db: Session = Depends(get_db)):
    try:
        chat_id = int(payload["chat_id"])
    except Exception as exc:
        raise HTTPException(400, "invalid payload") from exc

    user = _get_or_create_user(db, chat_id)
    sub = _get_sub(db, user.id)
    if not sub:
        return {"ok": False, "detail": "Subscription not found"}

    sub.cancel_at_period_end = False
    db.commit()
    return {"ok": True}


@router.post("/admin_give")
def admin_give(payload: AdminGiveIn, db: Session = Depends(get_db)):
    user = _get_or_create_user(db, payload.chat_id)
    sub = _get_sub(db, user.id)

    now = _now()
    end = now + timedelta(days=payload.days)

    if not sub:
        sub = Subscription(user_id=user.id, plan="Admin", status="active", current_period_end=end)
        db.add(sub)
    else:
        sub.plan = "Admin"
        sub.status = "active"
        sub.current_period_end = end
        sub.cancel_at_period_end = True
        sub.cp_sub_id = None

    credits = _get_or_create_credits(db, user.id)
    credits.img_limit_base = payload.generations
    if (credits.web_queries or 0) > credits.img_limit_base:
        credits.img_limit_base = credits.web_queries

    db.commit()
    return {
        "ok": True,
        "active_until": end.isoformat(),
        "generations": credits.img_limit_base,
        "used": credits.web_queries or 0,
    }


@router.post("/admin_cancel")
def admin_cancel(payload: dict, db: Session = Depends(get_db)):
    try:
        chat_id = int(payload["chat_id"])
    except Exception as exc:
        raise HTTPException(400, "invalid chat_id") from exc

    user = _get_or_create_user(db, chat_id)
    sub = _get_sub(db, user.id)
    if sub:
        db.delete(sub)

    credits = _get_or_create_credits(db, user.id)
    credits.img_limit_base = 0
    credits.msg_limit_base = 0
    credits.video_limit_base = 0

    db.commit()
    return {"ok": True}
