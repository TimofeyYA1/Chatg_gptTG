import sys
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

# Добавляем текущую директорию в путь, чтобы видеть модули проекта
sys.path.append(os.getcwd())

# Импортируем ваши модели и настройку БД
# (Убедитесь, что пути совпадают с вашей структурой папок внутри контейнера)
from db_adapter.database import SessionLocal
from db_adapter.models import User, Subscription, PremiumCredits

def give_premium_week(chat_id: int):
    print(f"🚀 Начинаем выдачу Премиума (7 дней) для ID: {chat_id}")
    
    # Создаем сессию БД
    db = SessionLocal()
    
    try:
        # 1. Ищем пользователя
        user = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
        
        if not user:
            print(f"⚠️ Пользователь {chat_id} не найден в базе. Сначала он должен запустить бота (/start).")
            return

        print(f"✅ Пользователь найден: ID {user.id}")

        # 2. Управление подпиской
        sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
        
        # Рассчитываем даты
        now = datetime.now(timezone.utc)
        end_date = now + timedelta(days=7)

        if not sub:
            print("🔹 Создаем новую запись подписки...")
            sub = Subscription(user_id=user.id)
            db.add(sub)
        else:
            print("🔹 Обновляем существующую подписку...")

        # Устанавливаем параметры "Week"
        sub.plan = "Week"
        sub.status = "active"
        sub.current_period_end = end_date
        sub.cancel_at_period_end = True # Ставим True, так как это ручная выдача (автосписания не будет)
        sub.cp_sub_id = None # Нет привязки к CloudPayments

        # 3. Начисление лимитов (Кредитов)
        credits = db.execute(select(PremiumCredits).where(PremiumCredits.user_id == user.id)).scalar_one_or_none()
        
        if not credits:
            credits = PremiumCredits(user_id=user.id)
            db.add(credits)
        
        # Лимит для тарифа Week (как в конфиге)
        LIMIT_WEEK = 150 
        credits.img_limit_base = LIMIT_WEEK
        
        # Опционально: сбросить счетчик использованных, если хотите дать "чистые" 150
        # credits.web_queries = 0 

        # 4. Сохраняем
        db.commit()
        
        print("-" * 30)
        print(f"🎉 УСПЕШНО!")
        print(f"Пользователь: {chat_id}")
        print(f"Тариф: Week (150 генераций)")
        print(f"Действует до: {end_date.strftime('%d.%m.%Y %H:%M')}")
        print("-" * 30)

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python give_premium.py <CHAT_ID>")
    else:
        try:
            target_chat_id = int(sys.argv[1])
            give_premium_week(target_chat_id)
        except ValueError:
            print("❌ Ошибка: Chat ID должен быть числом.")