from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from sqlalchemy import select

sys.path.append(os.getcwd())

from common.subscriptions import plan_title_ru, tier_code_from_plan, tier_name_ru  # noqa: E402
from db_adapter.database import SessionLocal  # noqa: E402
from db_adapter.models import Subscription, User  # noqa: E402


def _format_dt(dt):
    if not dt:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def list_users_with_subscription_levels(show_only_active: bool = False):
    db = SessionLocal()
    try:
        stmt = (
            select(User, Subscription)
            .outerjoin(Subscription, Subscription.user_id == User.id)
            .order_by(User.id.asc())
        )
        rows = db.execute(stmt).all()
        now = datetime.now(timezone.utc)

        print(f"rows={len(rows)}")
        print("-" * 120)
        print(f"{'user_id':<8} {'chat_id':<14} {'tier':<8} {'plan':<14} {'plan_title':<28} {'status':<10} {'until':<20} {'expired':<8}")
        print("-" * 120)

        for user, sub in rows:
            if sub:
                plan = sub.plan or "-"
                tier_code = tier_code_from_plan(sub.plan)
                tier = tier_name_ru(tier_code)
                plan_label = plan_title_ru(sub.plan)
                status = sub.status or "-"
                until = sub.current_period_end
                expired = False
                if until:
                    if until.tzinfo is None:
                        until = until.replace(tzinfo=timezone.utc)
                    expired = until < now

                if show_only_active:
                    if status != "active":
                        continue
                    if until and expired:
                        continue
            else:
                plan = "-"
                tier = "none"
                plan_label = "-"
                status = "-"
                until = None
                expired = False
                if show_only_active:
                    continue

            print(
                f"{user.id:<8} {str(user.chat_id):<14} {tier:<8} {plan:<14} {plan_label:<28} "
                f"{status:<10} {_format_dt(until):<20} {str(expired):<8}"
            )

        print("-" * 120)
    except Exception as exc:
        print(f"db error: {exc}")
    finally:
        db.close()


if __name__ == "__main__":
    only_active = "--active" in sys.argv
    list_users_with_subscription_levels(show_only_active=only_active)

