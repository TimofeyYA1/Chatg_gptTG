from __future__ import annotations
from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from db_adapter.database import get_db
from db_adapter.models import User, Subscription, PremiumCredits, Referral
from sqlalchemy import select
from common.config import settings
from pydantic import BaseModel


BONUS_DEFAULT_SUBSCRIPTION_CENTS = getattr(settings, "REFERRAL_SUBSCRIPTION_BONUS_CENTS", 100_00)

router = APIRouter( tags=["subscriptions"])

PLANS = {
    "Light": {"price_cents": 275_00, "limits": {"messages": 50 * 30,  "images": 500,  "video": 0}},
    "Max":   {"price_cents": 450_00, "limits": {"messages": 100 * 30, "images": 1000, "video": 10}},
    "Ultra": {"price_cents": 1333_00,"limits": {"messages": 500 * 30, "images": 2500, "video": 100}},
}
FREE_LIMITS = {"messages": 1, "images": 1, "video": 0}


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


def _apply_referral_subscription_bonus(
    db: Session,
    user: User,
) -> dict:
    """
    Если user пришёл по рефке и по нему ещё не выдавали
    бонус за платную подписку — начисляем +100⭐ обоим.

    Возвращаем словарь, чтобы бот мог отправить пуши.
    """

    bonus_cents = BONUS_DEFAULT_SUBSCRIPTION_CENTS
    if bonus_cents <= 0:
        return {"applied": False}

    # Ищем реферальную запись, где этот юзер был приглашённым
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

    # Начисляем бонус обоим
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
    price_cents: int

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
def set_plan(payload: SetPlanIn, db: Session = Depends(get_db)):
    """
    Покупка/продление на месяц:
      - списываем звёзды
      - продлеваем current_period_end
      - обновляем базовые лимиты в PremiumCredits под план
      - usage НЕ обнуляем руками здесь (можно добавить при желании)
    """
    # 1. Достаём поля из Pydantic-модели
    chat_id = payload.chat_id
    plan = payload.plan
    price_cents = payload.price_cents

    # 2. Валидируем план и цену
    if plan not in PLANS:
        raise HTTPException(status_code=400, detail="unknown plan")

    expected_price = PLANS[plan]["price_cents"]
    if price_cents != expected_price:
        raise HTTPException(status_code=400, detail="price mismatch")

    # 3. Ищем/создаём пользователя
    user = db.execute(
        select(User).where(User.chat_id == chat_id)
    ).scalar_one_or_none()
    if not user:
        user = User(chat_id=chat_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    # 4. Проверяем баланс
    current_balance = user.balance_cents or 0
    if current_balance < price_cents:
        raise HTTPException(status_code=402, detail="insufficient funds")

    user.balance_cents = current_balance - price_cents

    # 5. Работа с подпиской
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

    # 6. Обновляем лимиты по плану
    credits = _get_or_create_credits(db, user.id)
    plan_limits = PLANS[plan]["limits"]

    credits.msg_limit_base = plan_limits["messages"]
    credits.img_limit_base = plan_limits["images"]
    credits.video_limit_base = plan_limits["video"]

    db.commit()
    db.refresh(user)
    db.refresh(sub)
    db.refresh(credits)

    # 7. Применяем реферальный бонус за платную подписку
    referral_bonus = _apply_referral_subscription_bonus(db, user)

    return {
        "ok": True,
        "plan": plan,
        "referral_bonus": referral_bonus,
    }


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
