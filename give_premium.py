import sys
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

# Добавляем текущую директорию в путь
sys.path.append(os.getcwd())

from db_adapter.database import SessionLocal
from db_adapter.models import User, Subscription, PremiumCredits

# Конфигурация того, что мы выдаем (можно поменять лимиты тут)
TIER_CONFIG = {
    "std": {
        "plan_name": "Week_Std",  # Название в базе (как в subscriptions.py)
        "days": 7,
        "limit": 150              # Лимит генераций
    },
    "pro": {
        "plan_name": "Week_Pro",
        "days": 7,
        "limit": 150              # Лимит генераций (если у Pro он больше, измените тут)
    }
}

def give_premium(chat_id: int, tier_type: str = "std"):
    tier_key = tier_type.lower().strip()
    
    if tier_key not in TIER_CONFIG:
        print(f"❌ Ошибка: Неверный тип '{tier_type}'. Доступны: std, pro")
        return

    config = TIER_CONFIG[tier_key]
    plan_name = config["plan_name"]
    limit_val = config["limit"]
    days_val = config["days"]

    print(f"🚀 Выдача Премиума [{tier_key.upper()}] для ID: {chat_id}")
    
    db = SessionLocal()
    
    try:
        # 1. Ищем пользователя
        user = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
        
        if not user:
            print(f"⚠️ Пользователь {chat_id} не найден в базе.")
            return

        print(f"✅ Пользователь найден: ID {user.id}")

        # 2. Управление подпиской
        sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
        
        now = datetime.now(timezone.utc)
        end_date = now + timedelta(days=days_val)

        if not sub:
            print("🔹 Создаем новую запись подписки...")
            sub = Subscription(user_id=user.id)
            db.add(sub)
        else:
            print("🔹 Обновляем существующую подписку...")

        # Обновляем поля
        sub.plan = plan_name
        sub.status = "active"
        sub.current_period_end = end_date
        sub.cancel_at_period_end = True # Без автосписания
        sub.cp_sub_id = None 

        # 3. Начисление лимитов
        credits = db.execute(select(PremiumCredits).where(PremiumCredits.user_id == user.id)).scalar_one_or_none()
        
        if not credits:
            credits = PremiumCredits(user_id=user.id)
            db.add(credits)
        
        # Ставим лимит согласно тарифу
        credits.img_limit_base = limit_val
        
        # Если хотите сбрасывать потраченное при выдаче, раскомментируйте:
        # credits.web_queries = 0 

        db.commit()
        
        print("-" * 35)
        print(f"🎉 УСПЕШНО ВЫДАНО!")
        print(f"👤 User: {chat_id}")
        print(f"🏷  Plan: {plan_name} ({tier_key.upper()})")
        print(f"🖼  Limit: {limit_val} gen")
        print(f"⏳ Until: {end_date.strftime('%d.%m.%Y %H:%M')}")
        print("-" * 35)

    except Exception as e:
        print(f"❌ Ошибка БД: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    # Считывание аргументов командной строки
    if len(sys.argv) < 2:
        print("Использование: python give_premium.py <CHAT_ID> [std/pro]")
    else:
        try:
            target_chat_id = int(sys.argv[1])
            
            # Если есть второй аргумент, берем его, иначе 'std'
            target_tier = sys.argv[2] if len(sys.argv) > 2 else "std"
            
            give_premium(target_chat_id, target_tier)
            
        except ValueError:
            print("❌ Ошибка: Chat ID должен быть числом.")