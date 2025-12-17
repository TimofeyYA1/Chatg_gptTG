from __future__ import annotations

from datetime import datetime, timezone, timedelta

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.config import settings
from db_adapter.database import get_db
from db_adapter.models import User, Subscription, PremiumCredits, Referral


BONUS_DEFAULT_SUBSCRIPTION_CENTS = getattr(settings, "REFERRAL_SUBSCRIPTION_BONUS_CENTS", 100_00)

router = APIRouter(tags=["subscriptions"])


PLANS = {
    # Лимиты: Неделя=150, Месяц=600, Год=7200
    "Week":  {"price_cents": 300_00,  "rub_price": 399,  "limits": {"messages": 0, "images": 150,  "video": 0}, "duration": {"days": 7}},
    "Month": {"price_cents": 900_00,  "rub_price": 1199, "limits": {"messages": 0, "images": 600,  "video": 0}, "duration": {"months": 1}},
    "Year":  {"price_cents": 4500_00, "rub_price": 5999, "limits": {"messages": 0, "images": 7200, "video": 0}, "duration": {"years": 1}},
}

PLAN_ALIASES = {
    "Light": "Week",
    "Max": "Month",
    "Ultra": "Year",
    "week": "Week",
    "month": "Month",
    "year": "Year",
    "Week": "Week",
    "Month": "Month",
    "Year": "Year",
}

def _norm_plan(p: str) -> str:
    p = (p or "").strip()
    return PLAN_ALIASES.get(p, p)


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
    return db.execute(select(Subscription).where(Subscription.user_id == user_id)).scalar_one_or_none()


def _get_or_create_credits(db: Session, user_id: int) -> PremiumCredits:
    p = db.execute(select(PremiumCredits).where(PremiumCredits.user_id == user_id)).scalar_one_or_none()
    if p:
        return p
    p = PremiumCredits(user_id=user_id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _apply_referral_subscription_bonus(db: Session, user: User) -> dict:
    bonus_cents = BONUS_DEFAULT_SUBSCRIPTION_CENTS
    if bonus_cents <= 0:
        return {"applied": False}

    ref = db.execute(
        select(Referral).where(
            Referral.invited_user_id == user.id,
            Referral.bonus_awarded.is_(False),
        )
    ).scalar_one_or_none()

    if not ref:
        return {"applied": False}

    referrer = db.get(User, ref.referrer_id)
    if not referrer:
        return {"applied": False}

    referrer.balance_cents = (referrer.balance_cents or 0) + bonus_cents
    user.balance_cents = (user.balance_cents or 0) + bonus_cents

    ref.bonus_awarded = True

    db.commit()
    db.refresh(ref)
    db.refresh(user)
    db.refresh(referrer)

    return {
        "applied": True,
        "bonus_cents": bonus_cents,
        "referrer_chat_id": referrer.chat_id,
        "invited_chat_id": user.chat_id,
    }


class SetPlanIn(BaseModel):
    chat_id: int
    plan: str
    price_cents: int | None = None


@router.get("/summary/{chat_id}")
def summary(chat_id: int, db: Session = Depends(get_db)):
    """
    Возвращает статистику для отображения в боте.
    Здесь же происходит проверка истечения срока подписки.
    """
    user = _get_or_create_user(db, chat_id)
    sub = _get_sub(db, user.id)
    credits = _get_or_create_credits(db, user.id)

    # Проверка истечения времени
    if sub and sub.current_period_end and _now() >= sub.current_period_end:
        # Обнуляем лимиты, так как подписка сгорела
        credits.msg_limit_base = 0
        credits.img_limit_base = 0
        credits.video_limit_base = 0
        # Удаляем подписку (переводим во free)
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
def set_plan(payload: SetPlanIn, db: Session = Depends(get_db)):
    chat_id = payload.chat_id
    plan = _norm_plan(payload.plan)
    price_cents = payload.price_cents

    if plan not in PLANS:
        raise HTTPException(status_code=400, detail="unknown plan")

    expected_price = PLANS[plan]["price_cents"]
    if price_cents is not None and price_cents != expected_price:
        raise HTTPException(status_code=400, detail="price mismatch")
    price_cents = expected_price

    user = _get_or_create_user(db, chat_id)

    # ПРОВЕРКА: Если уже есть активная подписка — запрещаем покупку
    sub = _get_sub(db, user.id)
    if sub and sub.current_period_end and sub.current_period_end > _now():
        raise HTTPException(status_code=400, detail="subscription_already_active")

    # Проверка баланса
    current_balance = user.balance_cents or 0
    if current_balance < price_cents:
        raise HTTPException(status_code=402, detail="insufficient funds")
    user.balance_cents = current_balance - price_cents

    start_from = _now()
    
    dur = PLANS[plan]["duration"]
    if "days" in dur:
        end = start_from + timedelta(days=int(dur["days"]))
    elif "months" in dur:
        end = start_from + relativedelta(months=int(dur["months"]))
    elif "years" in dur:
        end = start_from + relativedelta(years=int(dur["years"]))
    else:
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
        # Этого блока по идее не достигнем из-за проверки выше, но оставим для надежности
        sub.plan = plan
        sub.status = "active"
        sub.current_period_end = end
        sub.cancel_at_period_end = False

    # === ОБНОВЛЯЕМ ЛИМИТЫ И СБРАСЫВАЕМ СЧЕТЧИК ===
    credits = _get_or_create_credits(db, user.id)
    plan_limits = PLANS[plan]["limits"]
    
    credits.msg_limit_base = plan_limits["messages"]
    credits.img_limit_base = plan_limits["images"]
    credits.video_limit_base = plan_limits["video"]
    
    # Сбрасываем счетчик при покупке
    credits.web_queries = 0  

    db.commit()
    db.refresh(user)
    db.refresh(sub)
    db.refresh(credits)

    referral_bonus = _apply_referral_subscription_bonus(db, user)

    return {
        "ok": True,
        "plan": plan,
        "active_until": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "referral_bonus": referral_bonus,
    }


@router.post("/cancel")
def cancel(payload: dict, db: Session = Depends(get_db)):
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