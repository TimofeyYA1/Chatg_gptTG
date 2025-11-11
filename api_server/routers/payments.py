from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits

router = APIRouter()

def _get_or_create_user(db: Session, chat_id: int) -> User:
    user = db.query(User).filter(User.chat_id == chat_id).first()
    if not user:
        user = User(chat_id=chat_id, role="free", balance_cents=0)
        db.add(user); db.flush()
        db.add(PremiumCredits(user_id=user.id))
        db.commit()
        db.refresh(user)
    return user

@router.get("/balance/{chat_id}")
def get_balance(chat_id: int, db: Session = Depends(get_db)):
    u = _get_or_create_user(db, chat_id)
    return {"balance_cents": u.balance_cents}

@router.post("/balance/topup")
def topup(payload: dict, db: Session = Depends(get_db)):
    chat_id = int(payload["chat_id"])
    amount = int(payload["amount"])
    u = _get_or_create_user(db, chat_id)
    u.balance_cents += amount
    db.commit()
    return {"balance_cents": u.balance_cents}

@router.post("/addons/buy")
def buy_addon(payload: dict, db: Session = Depends(get_db)):
    """
    payload: { chat_id, kind: "messages"|"images"|"video", qty: int, price_cents: int }
    Докидываем в PremiumCredits:
      messages -> web_queries_left += qty
      images   -> image_credits   += qty
      video    -> video_seconds_left += qty  (тут qty трактуем как "роликов")
    """
    chat_id = int(payload.get("chat_id"))
    kind = str(payload.get("kind"))
    qty = int(payload.get("qty", 0))
    price = int(payload.get("price_cents", 0))

    if kind not in {"messages", "images", "video"}:
        raise HTTPException(400, "invalid kind")
    if qty <= 0 or price <= 0:
        raise HTTPException(400, "invalid qty/price")

    u = _get_or_create_user(db, chat_id)
    if u.balance_cents < price:
        raise HTTPException(402, "insufficient balance")

    p = u.premium
    if kind == "messages":
        p.web_queries_left = (p.web_queries_left or 0) + qty
    elif kind == "images":
        p.image_credits = (p.image_credits or 0) + qty
    else:
        p.video_seconds_left = (p.video_seconds_left or 0) + qty

    u.balance_cents -= price
    db.commit()
    return {"ok": True, "balance_cents": u.balance_cents, "addons": {
        "messages": p.web_queries_left or 0,
        "images": p.image_credits or 0,
        "video": p.video_seconds_left or 0,
    }}
