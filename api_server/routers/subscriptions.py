from __future__ import annotations

from datetime import datetime, timezone, timedelta

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.config import settings
from db_adapter.database import get_db
from db_adapter.models import User, Subscription, PremiumCredits
from api_server.services.cloudpayments import cp_service 


router = APIRouter(tags=["subscriptions"])


PLANS = {
    # --- STANDARD ---
    "Week_Std":  {"price_cents": 399_00,  "rub_price": 399,  "limits": {"messages": 0, "images": 150,  "video": 0}, "duration": {"days": 7}},
    "Month_Std": {"price_cents": 1199_00, "rub_price": 1199, "limits": {"messages": 0, "images": 600,  "video": 0}, "duration": {"months": 1}},
    "Year_Std":  {"price_cents": 5999_00, "rub_price": 5999, "limits": {"messages": 0, "images": 7200, "video": 0}, "duration": {"years": 1}},

    # --- PRO ---
    "Week_Pro":  {"price_cents": 799_00,  "rub_price": 799,  "limits": {"messages": 0, "images": 150,  "video": 0}, "duration": {"days": 7}},
    "Month_Pro": {"price_cents": 2399_00, "rub_price": 2399, "limits": {"messages": 0, "images": 600,  "video": 0}, "duration": {"months": 1}},
    "Year_Pro":  {"price_cents": 11999_00, "rub_price": 11999, "limits": {"messages": 0, "images": 7200, "video": 0}, "duration": {"years": 1}},
}

PLAN_ALIASES = {
    "Week": "Week_Std", "Month": "Month_Std", "Year": "Year_Std",
    "week": "Week_Std", "month": "Month_Std", "year": "Year_Std",
    "Week_Std": "Week_Std", "Month_Std": "Month_Std", "Year_Std": "Year_Std",
    "Week_Pro": "Week_Pro", "Month_Pro": "Month_Pro", "Year_Pro": "Year_Pro",
    "Light": "Week_Std", "Max": "Month_Std", "Ultra": "Year_Std",
}

def _norm_plan(p: str) -> str:
    p = (p or "").strip()
    return PLAN_ALIASES.get(p, p)

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _get_or_create_user(db: Session, chat_id: int) -> User:
    u = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
    if u: return u
    u = User(chat_id=chat_id, role="free", balance_cents=0)
    db.add(u); db.commit(); db.refresh(u)
    return u

def _get_sub(db: Session, user_id: int) -> Subscription | None:
    return db.execute(select(Subscription).where(Subscription.user_id == user_id)).scalar_one_or_none()

def _get_or_create_credits(db: Session, user_id: int) -> PremiumCredits:
    p = db.execute(select(PremiumCredits).where(PremiumCredits.user_id == user_id)).scalar_one_or_none()
    if p: return p
    p = PremiumCredits(user_id=user_id)
    db.add(p); db.commit(); db.refresh(p)
    return p

class SetPlanIn(BaseModel):
    chat_id: int
    plan: str
    price_cents: int | None = None

@router.get("/summary/{chat_id}")
def summary(chat_id: int, db: Session = Depends(get_db)):
    user = _get_or_create_user(db, chat_id)
    sub = _get_sub(db, user.id)
    credits = _get_or_create_credits(db, user.id)

    # Проверка истечения времени
    if sub and sub.current_period_end and _now() >= sub.current_period_end:
        # Сжигаем ВСЕ лимиты
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
        # Цена продления
        plan_info = PLANS.get(role, {})
        renew_price = plan_info.get("rub_price", 0)

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
    chat_id = payload.chat_id
    plan = _norm_plan(payload.plan)
    price_cents = payload.price_cents

    if plan not in PLANS: raise HTTPException(400, "unknown plan")
    expected = PLANS[plan]["price_cents"]
    if price_cents is not None and price_cents != expected: raise HTTPException(400, "price mismatch")
    
    user = _get_or_create_user(db, chat_id)
    
    if (user.balance_cents or 0) < expected: raise HTTPException(402, "insufficient funds")
    user.balance_cents -= expected

    sub = _get_sub(db, user.id)
    start = _now()
    if sub and sub.current_period_end and sub.current_period_end > start:
        start = sub.current_period_end # Продление

    dur = PLANS[plan]["duration"]
    if "days" in dur: end = start + timedelta(days=int(dur["days"]))
    elif "months" in dur: end = start + relativedelta(months=int(dur["months"]))
    else: end = start + relativedelta(years=int(dur["years"]))

    if not sub:
        sub = Subscription(user_id=user.id, plan=plan, status="active", current_period_end=end)
        db.add(sub)
    else:
        sub.plan = plan; sub.status = "active"; sub.current_period_end = end; sub.cancel_at_period_end = False

    credits = _get_or_create_credits(db, user.id)
    pl = PLANS[plan]["limits"]
    credits.msg_limit_base = pl["messages"]
    credits.img_limit_base = pl["images"]
    credits.video_limit_base = pl["video"]
    
    # Сброс использования при НОВОЙ покупке/продлении
    credits.web_queries = 0 
    
    db.commit()
    return {"ok": True, "plan": plan}

@router.post("/cancel")
async def cancel(payload: dict, db: Session = Depends(get_db)):
    try: chat_id = int(payload["chat_id"])
    except: raise HTTPException(400, "invalid payload")
    
    user = _get_or_create_user(db, chat_id)
    sub = _get_sub(db, user.id)
    
    if not sub: raise HTTPException(400, "no sub")
    
    # 1. Отменяем в CloudPayments (если есть ID)
    if sub.cp_sub_id:
        await cp_service.cancel_subscription(sub.cp_sub_id)
        sub.cp_sub_id = None # Стираем ID, так как подписка убита в CP

    # 2. Обновляем локально
    sub.cancel_at_period_end = True
    db.commit()
    
    return {"ok": True}