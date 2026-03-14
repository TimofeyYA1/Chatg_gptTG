from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

sys.path.append(os.getcwd())

from common.subscriptions import get_plan_spec, tier_name_ru  # noqa: E402
from db_adapter.database import SessionLocal  # noqa: E402
from db_adapter.models import PremiumCredits, Subscription, User  # noqa: E402

TIER_TO_PLAN = {
    "start": "Month_Std",
    "std": "Month_Std",
    "pro": "Month_Std2",
    "elite": "Month_Pro",
}


def give_premium(chat_id: int, tier_type: str = "start", days: int = 30) -> None:
    tier_key = (tier_type or "start").strip().lower()
    plan_key = TIER_TO_PLAN.get(tier_key)
    if not plan_key:
        print(f"invalid tier: {tier_type}. allowed: start, pro, elite")
        return

    spec = get_plan_spec(plan_key)
    if not spec:
        print(f"unknown plan config for tier: {tier_type}")
        return

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
        if not user:
            print(f"user {chat_id} not found")
            return

        sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        end_date = now + timedelta(days=max(1, int(days)))

        if not sub:
            sub = Subscription(user_id=user.id)
            db.add(sub)

        sub.plan = plan_key
        sub.status = "active"
        sub.current_period_end = end_date
        sub.cancel_at_period_end = True
        sub.cp_sub_id = None

        credits = db.execute(select(PremiumCredits).where(PremiumCredits.user_id == user.id)).scalar_one_or_none()
        if not credits:
            credits = PremiumCredits(user_id=user.id)
            db.add(credits)

        credits.img_limit_base = spec.images_limit
        if (credits.web_queries or 0) > credits.img_limit_base:
            credits.img_limit_base = credits.web_queries

        db.commit()
        print("ok")
        print(f"chat_id={chat_id}")
        print(f"tier={tier_name_ru(spec.tier)}")
        print(f"plan={plan_key}")
        print(f"limit={credits.img_limit_base}")
        print(f"until={end_date.isoformat()}")
    except Exception as exc:
        db.rollback()
        print(f"db error: {exc}")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python give_premium.py <CHAT_ID> [start|pro|elite] [days]")
        raise SystemExit(1)

    try:
        target_chat_id = int(sys.argv[1])
    except ValueError:
        print("chat id must be int")
        raise SystemExit(1)

    target_tier = sys.argv[2] if len(sys.argv) > 2 else "start"
    target_days = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    give_premium(target_chat_id, target_tier, target_days)

