import sys
import os
from sqlalchemy import select

# Добавляем текущую директорию в путь
sys.path.append(os.getcwd())

from db_adapter.database import SessionLocal
from db_adapter.models import User, PremiumCredits, Subscription

def full_delete_user(chat_id: int):
    print(f"💀 Поиск пользователя для удаления: {chat_id}")
    
    db = SessionLocal()
    
    try:
        # 1. Ищем пользователя
        user = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
        
        if not user:
            print(f"⚠️ Пользователь с chat_id {chat_id} не найден в базе.")
            return

        print(f"🛑 НАЙДЕН ПОЛЬЗОВАТЕЛЬ:")
        print(f"ID: {user.id}")
        print(f"Chat ID: {user.chat_id}")
        print("-" * 30)
        
        print(f"🗑 Очистка зависимых данных...")

        # --- ЯВНОЕ УДАЛЕНИЕ ЗАВИСИМОСТЕЙ ---
        # Это нужно, чтобы SQLAlchemy не пыталась сделать UPDATE user_id = NULL
        
        # 1. Удаляем PremiumCredits
        credits = db.execute(select(PremiumCredits).where(PremiumCredits.user_id == user.id)).scalar_one_or_none()
        if credits:
            db.delete(credits)
            print("   - Удалены кредиты/лимиты")

        # 2. Удаляем Subscription
        sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
        if sub:
            db.delete(sub)
            print("   - Удалена подписка")

        # Остальные таблицы (чаты, сообщения) обычно связаны через One-to-Many 
        # и удалятся каскадно нормально, но для One-to-One (кредиты) нужно ручное удаление в ORM.

        # 3. Удаляем самого пользователя
        print(f"🗑 Удаляем запись пользователя...")
        db.delete(user)
        
        db.commit()

        print(f"✅ Пользователь {chat_id} и все его данные полностью уничтожены.")

    except Exception as e:
        print(f"❌ Ошибка при удалении: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python delete_user.py <CHAT_ID>")
    else:
        try:
            target_chat_id = int(sys.argv[1])
            full_delete_user(target_chat_id)
        except ValueError:
            print("❌ Ошибка: Chat ID должен быть числом.")