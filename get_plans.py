import sys
import os
from datetime import datetime, timezone
from sqlalchemy import select

# Добавляем текущую директорию в путь
sys.path.append(os.getcwd())

from db_adapter.database import SessionLocal
from db_adapter.models import User, Subscription

# Маппинг названий планов -> "уровень"
# (подстрой под свои реальные значения plan в базе)
PLAN_TO_TIER = {
    "Week_Std": "std",
    "Week_Pro": "pro",
}

def format_dt(dt):
    if not dt:
        return "-"
    # если в базе naive datetime, можно привести к UTC для единообразия
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

def list_users_with_subscription_levels(show_only_active: bool = False):
    db = SessionLocal()
    try:
        # LEFT JOIN: покажем и тех, у кого подписки нет
        stmt = (
            select(User, Subscription)
            .outerjoin(Subscription, Subscription.user_id == User.id)
            .order_by(User.id.asc())
        )

        rows = db.execute(stmt).all()

        now = datetime.now(timezone.utc)

        print(f"📋 Всего записей: {len(rows)}")
        print("-" * 90)
        print(f"{'user_id':<8} {'chat_id':<14} {'tier':<6} {'plan':<12} {'status':<10} {'until':<20} {'expired':<8}")
        print("-" * 90)

        for user, sub in rows:
            if sub:
                plan = sub.plan or "-"
                tier = PLAN_TO_TIER.get(sub.plan, "unknown" if sub.plan else "-")
                status = sub.status or "-"
                until = sub.current_period_end
                expired = False

                if until:
                    # Нормализуем tz
                    if until.tzinfo is None:
                        until = until.replace(tzinfo=timezone.utc)
                    expired = until < now

                if show_only_active:
                    # активная = статус active и не просрочена (если есть until)
                    if status != "active":
                        continue
                    if until and expired:
                        continue
            else:
                plan = "-"
                tier = "none"
                status = "-"
                until = None
                expired = False

                if show_only_active:
                    continue

            print(
                f"{user.id:<8} {str(user.chat_id):<14} {tier:<6} {plan:<12} {status:<10} "
                f"{format_dt(until):<20} {str(expired):<8}"
            )

        print("-" * 90)

    except Exception as e:
        print(f"❌ Ошибка БД: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    # Опциональный флаг: только активные
    # usage: python list_users_subs.py [--active]
    only_active = "--active" in sys.argv
    list_users_with_subscription_levels(show_only_active=only_active)
