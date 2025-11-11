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

@router.post("/increment")
def increment_usage(payload: dict, db: Session = Depends(get_db)):
    """
    payload: { chat_id: int, kind: "messages"|"images"|"video", value?: int }
    messages -> PremiumCredits.total_queries
    images   -> PremiumCredits.web_queries
    """
    chat_id = int(payload.get("chat_id"))
    kind = str(payload.get("kind"))
    value = int(payload.get("value", 1))
    if value <= 0:
        raise HTTPException(400, "value must be positive")
    if kind not in {"messages", "images", "video"}:
        raise HTTPException(400, "invalid kind")

    user = _get_or_create_user(db, chat_id)
    p = user.premium
    if kind == "messages":
        p.total_queries = (p.total_queries or 0) + value
    elif kind == "images":
        p.web_queries = (p.web_queries or 0) + value
    elif kind == "video":
        # счётчик использования видео пока не ведём
        pass

    db.commit()
    return {"ok": True}
