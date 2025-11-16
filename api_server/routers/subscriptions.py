from __future__ import annotations
from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from db_adapter.database import get_db
from db_adapter.models import User, Subscription, PremiumCredits

router = APIRouter( tags=["subscriptions"])

PLANS = {
    "Light": {"price_cents": 275_00, "limits": {"messages": 50 * 30,  "images": 500,  "video": 0}},
    "Max":   {"price_cents": 450_00, "limits": {"messages": 100 * 30, "images": 1000, "video": 10}},
    "Ultra": {"price_cents": 1333_00,"limits": {"messages": 500 * 30, "images": 2500, "video": 100}},
}
FREE_LIMITS = {"messages": 0, "images": 0, "video": 0}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_create_user(db: Session, chat_id: int) -> User:
    u = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
    if u:
        return u
    u = User(chat_id=chat_id, role="free", balance_cents=0)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _get_sub(db: Session, user_id: int) -> Subscription | None:
    return db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    ).scalar_one_or_none()


def _get_or_create_credits(db: Session, user_id: int) -> PremiumCredits:
    p = db.execute(
        select(PremiumCredits).where(PremiumCredits.user_id == user_id)
    ).scalar_one_or_none()
    if p:
        return p
    p = PremiumCredits(user_id=user_id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/summary/{chat_id}")
def summary(chat_id: int, db: Session = Depends(get_db)):
    """
    Возвращает:
      - role
      - balance_cents
      - active_until, auto_renew
      - limits: базовые лимиты (из PremiumCredits, а не из PLANS напрямую)
      - usage: фактическое использование
      - addons: докупленные
      - totals: base + addons
    """
    user = _get_or_create_user(db, chat_id)
    sub = _get_sub(db, user.id)
    credits = _get_or_create_credits(db, user.id)

    # ленивое истечение подписки
    if sub and sub.current_period_end and _now() >= sub.current_period_end:
        # при окончании плана обнуляем базовые лимиты
        credits.msg_limit_base = 0
        credits.img_limit_base = 0
        credits.video_limit_base = 0

        db.delete(sub)
        db.commit()
        sub = None

    if not sub:
        role = "free"
        active_until = None
        auto_renew = False
    else:
        role = sub.plan or "free"
        active_until = sub.current_period_end
        auto_renew = not bool(sub.cancel_at_period_end)

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
        "limits": limits,
        "usage": usage,
        "addons": addons,
        "totals": totals,
    }


@router.post("/set_plan")
def set_plan(payload: dict, db: Session = Depends(get_db)):
    """
    Покупка/продление на месяц:
      - списываем звёзды
      - продлеваем current_period_end
      - обновляем базовые лимиты в PremiumCredits под план
      - usage НЕ обнуляем руками здесь (можно добавить при желании)
    """
    try:
        chat_id = int(payload["chat_id"])
        plan = str(payload["plan"])
        price_cents = int(payload["price_cents"])
    except Exception:
        raise HTTPException(400, "invalid payload")

    if plan not in PLANS:
        raise HTTPException(400, "unknown plan")
    if price_cents != PLANS[plan]["price_cents"]:
        raise HTTPException(400, "price mismatch")

    user = _get_or_create_user(db, chat_id)
    if user.balance_cents < price_cents:
        raise HTTPException(402, "insufficient funds")

    user.balance_cents -= price_cents

    sub = _get_sub(db, user.id)
    start_from = _now()
    if sub and sub.current_period_end and sub.current_period_end > start_from:
        start_from = sub.current_period_end

    end = start_from + relativedelta(months=1)

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

    # подтягиваем лимиты плана в PremiumCredits
    credits = _get_or_create_credits(db, user.id)
    plan_limits = PLANS[plan]["limits"]

    credits.msg_limit_base = plan_limits["messages"]
    credits.img_limit_base = plan_limits["images"]
    credits.video_limit_base = plan_limits["video"]

    db.commit()
    return {"ok": True, "plan": plan, "active_until": end.isoformat()}


@router.post("/cancel")
def cancel(payload: dict, db: Session = Depends(get_db)):
    """
    Отмена автопродления:
      - флаг cancel_at_period_end = True
      - статус 'canceled', доступ остаётся до current_period_end
    """
    try:
        chat_id = int(payload["chat_id"])
    except Exception:
        raise HTTPException(400, "invalid payload")

    user = _get_or_create_user(db, chat_id)
    sub = _get_sub(db, user.id)
    if not sub or not sub.current_period_end:
        raise HTTPException(400, "no active subscription")

    sub.cancel_at_period_end = True
    sub.status = "canceled"
    db.commit()

    return {
        "ok": True,
        "plan": sub.plan,
        "active_until": sub.current_period_end.isoformat(),
        "will_stop_at_period_end": True,
    }
