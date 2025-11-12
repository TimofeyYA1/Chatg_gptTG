from __future__ import annotations
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from db_adapter.database import get_db
from db_adapter.models import User, Subscription

router = APIRouter()

# Тарифы: цена и базовые лимиты (если где-то ещё считаете usage/addons — не трогаем)
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
    u = User(chat_id=chat_id)
    db.add(u); db.commit(); db.refresh(u)
    return u

def _get_sub(db: Session, user_id: int) -> Subscription | None:
    return db.execute(select(Subscription).where(Subscription.user_id == user_id)).scalar_one_or_none()

@router.get("/summary/{chat_id}")
def sub_summary(chat_id: int, db: Session = Depends(get_db)):
    """
    Возвращает текущее состояние подписки:
    - role: "free" или план
    - active_until: ISO дата конца периода (если есть)
    - auto_renew: True если НЕ стоит cancel_at_period_end
    - limits: базовые лимиты текущего плана (или FREE_LIMITS)
    """
    user = _get_or_create_user(db, chat_id)
    sub = _get_sub(db, user.id)

    # ленивое истечение: если период закончился — убираем запись
    if sub and sub.current_period_end and _now() >= sub.current_period_end:
        db.delete(sub)
        db.commit()
        sub = None

    if not sub:
        role = "free"
        active_until = None
        auto_renew = False
        limits = FREE_LIMITS
    else:
        role = sub.plan or "free"
        active_until = sub.current_period_end
        auto_renew = not bool(sub.cancel_at_period_end)
        limits = PLANS.get(role, {}).get("limits", FREE_LIMITS)

    return {
        "role": role,
        "balance_cents": user.balance_cents,
        "active_until": active_until.isoformat() if active_until else None,
        "auto_renew": auto_renew,
        "limits": limits,
    }

@router.post("/set_plan")
def set_plan(payload: dict, db: Session = Depends(get_db)):
    """
    Покупка/продление на месяц:
    - если текущая подписка ещё активна, продлеваем от current_period_end
    - иначе — от текущего момента
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

    # списываем средства
    user.balance_cents -= price_cents

    sub = _get_sub(db, user.id)
    start_from = _now()
    if sub and sub.current_period_end and sub.current_period_end > start_from:
        # продление от конца текущего оплаченного периода
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
        sub.cancel_at_period_end = False  # включили автопродление

    db.commit()
    return {"ok": True, "plan": plan, "active_until": end.isoformat()}

@router.post("/cancel")
def cancel(payload: dict, db: Session = Depends(get_db)):
    """
    Отмена автопродления:
    - помечаем cancel_at_period_end = True
    - статус 'canceled', но доступ сохраняется до current_period_end
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
