from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits
from common.config import settings

router = APIRouter()

def _get_or_create_user(db: Session, chat_id: int) -> User:
    user = db.query(User).filter(User.chat_id == chat_id).first()
    if not user:
        user = User(chat_id=chat_id, role="free", balance_cents=0)
        db.add(user)
        db.flush()
        db.add(PremiumCredits(
            user_id=user.id,
            web_queries_left=settings.ONBOARDING_PREMIUM_QUERIES,
            image_credits=settings.FREE_IMAGE_CREDITS,
            video_seconds_left=settings.FREE_VIDEO_SECONDS
        ))
        db.commit()
    return user

@router.get("/profile/{chat_id}")
def profile(chat_id: int, db: Session = Depends(get_db)):
    user = _get_or_create_user(db, chat_id)
    p = user.premium
    return {
        "chat_id": user.chat_id,
        "role": user.role,
        "balance_cents": user.balance_cents,
        "premium": {
            "web_queries_left": p.web_queries_left,
            "image_credits": p.image_credits,
            "video_seconds_left": p.video_seconds_left,
            "total_queries": p.total_queries,
            "web_queries": p.web_queries,
        }
    }
