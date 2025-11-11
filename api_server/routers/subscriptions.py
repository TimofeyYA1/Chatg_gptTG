from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits

router = APIRouter()

VALID_PLANS = {"free", "Light", "Max", "Ultra"}

# Базовые лимиты по плану
PLAN_LIMITS = {
    "free":  {"messages": 0,   "images": 0,    "video": 0},
    "Light": {"messages": 50,  "images": 500,  "video": 0},
    "Max":   {"messages": 100, "images": 1000, "video": 10},
    "Ultra": {"messages": 500, "images": 2500, "video": 100},
}

def _get_or_create_user(db: Session, chat_id: int) -> User:
    user = db.query(User).filter(User.chat_id == chat_id).first()
    if not user:
        user = User(chat_id=chat_id, role="free", balance_cents=0)
        db.add(user); db.flush()
        db.add(PremiumCredits(user_id=user.id))
        db.commit()
        db.refresh(user)
    return user

@router.get("/{chat_id}")
def get_subscription(chat_id: int, db: Session = Depends(get_db)):
    user = _get_or_create_user(db, chat_id)
    return {"role": user.role, "balance_cents": user.balance_cents}

@router.get("/summary/{chat_id}")
def subscription_summary(chat_id: int, db: Session = Depends(get_db)):
    """
    Возвращает:
      - role, balance
      - usage: {messages, images, video}
      - limits: базовые лимиты плана
      - addons: сколько ДОКУПЛЕНО (messages/images/video)
      - totals: лимиты с учётом докупленного
    Соглашения по полям PremiumCredits:
      total_queries — израсходовано сообщений
      web_queries   — израсходовано изображений
      web_queries_left — ДОКУПЛЕНО сообщений
      image_credits    — ДОКУПЛЕНО изображений
      video_seconds_left — ДОКУПЛЕНО видео (шт.)
    """
    user = _get_or_create_user(db, chat_id)
    p = user.premium
    base = PLAN_LIMITS.get(user.role, PLAN_LIMITS["free"])

    addons = {
        "messages": p.web_queries_left or 0,
        "images":   p.image_credits   or 0,
        "video":    p.video_seconds_left or 0,
    }
    usage = {
        "messages": p.total_queries or 0,
        "images":   p.web_queries   or 0,
        "video":    0,  # пока не считаем
    }
    totals = {
        "messages": base["messages"] + addons["messages"],
        "images":   base["images"] + addons["images"],
        "video":    base["video"] + addons["video"],
    }

    return {
        "role": user.role,
        "balance_cents": user.balance_cents,
        "limits": base,
        "addons": addons,
        "usage": usage,
        "totals": totals,
        "period": {"from": None, "to": None, "is_infinite": True},
    }

@router.post("/set_plan")
def set_plan(payload: dict, db: Session = Depends(get_db)):
    chat_id = int(payload.get("chat_id"))
    plan = str(payload.get("plan"))
    price = int(payload.get("price_cents", 0))
    if plan not in VALID_PLANS - {"free"}:
        raise HTTPException(400, "invalid plan")
    if price <= 0:
        raise HTTPException(400, "invalid price")

    user = _get_or_create_user(db, chat_id)
    if user.balance_cents < price:
        raise HTTPException(402, "insufficient balance")

    user.balance_cents -= price
    user.role = plan
    db.commit()
    return {"ok": True, "role": user.role, "balance_cents": user.balance_cents}

@router.post("/cancel")
def cancel(payload: dict, db: Session = Depends(get_db)):
    chat_id = int(payload.get("chat_id"))
    user = _get_or_create_user(db, chat_id)
    user.role = "free"
    db.commit()
    return {"ok": True, "role": user.role, "balance_cents": user.balance_cents}
