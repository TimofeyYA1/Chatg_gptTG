import sys
import os

# Добавляем корневую директорию проекта в путь импорта, 
# чтобы Python видел папку db_adapter
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from db_adapter.database import SessionLocal
from db_adapter.models import User, Subscription, PremiumCredits, ChatSession, ChatMessage

def delete_user_by_chat_id(chat_id: int):
    db = SessionLocal()
    try:
        print(f"🔍 Ищу пользователя с chat_id: {chat_id}...")
        
        user = db.query(User).filter(User.chat_id == chat_id).first()
        
        if not user:
            print(f"❌ Пользователь с chat_id {chat_id} не найден в базе.")
            return

        print(f"✅ Нашел: ID {user.id}, Username: {user.username}, Role: {user.role}")
        print("🗑 Удаляю данные...")

        # SQLAlchemy обычно настроена на каскадное удаление, 
        # но для надежности (чтобы избежать Foreign Key ошибок) удалим зависимости явно:
        
        # 1. Удаляем подписку
        sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
        if sub:
            db.delete(sub)
            print("   - Подписка удалена")

        # 2. Удаляем кредиты
        credits = db.query(PremiumCredits).filter(PremiumCredits.user_id == user.id).first()
        if credits:
            db.delete(credits)
            print("   - Кредиты удалены")

        # 3. Удаляем чаты и сообщения (если есть)
        sessions = db.query(ChatSession).filter(ChatSession.user_id == user.id).all()
        for s in sessions:
            db.query(ChatMessage).filter(ChatMessage.session_id == s.id).delete()
            db.delete(s)
        if sessions:
            print(f"   - Чаты ({len(sessions)}) удалены")

        # 4. Удаляем самого юзера
        db.delete(user)
        db.commit()
        
        print(f"✨ УСПЕШНО! Пользователь {chat_id} полностью стерт. Для бота он теперь новый.")

    except Exception as e:
        print(f"❌ Ошибка при удалении: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python tools/reset_user.py <TELEGRAM_ID>")
        sys.exit(1)
    
    try:
        target_chat_id = int(sys.argv[1])
        delete_user_by_chat_id(target_chat_id)
    except ValueError:
        print("❌ Ошибка: ID должен быть числом.")