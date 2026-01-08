import sys
from sqlalchemy import select
from db_adapter.database import SessionLocal
from db_adapter.models import User, PremiumCredits, Subscription

def remove_premium(chat_id: int):
    db = SessionLocal()
    try:
        print(f"🔍 Поиск пользователя {chat_id}...")
        user = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()

        if not user:
            print(f"❌ Пользователь с chat_id {chat_id} не найден.")
            return

        print(f"Пользователь найден (Internal ID: {user.id}). Снимаем премиум...")

        # 1. Сбрасываем роль на free
        user.role = "free"

        # 2. Обнуляем лимиты подписки (PremiumCredits)
        # Мы обнуляем только _base лимиты. Докупленные пакеты (image_credits) оставляем.
        credits = db.execute(select(PremiumCredits).where(PremiumCredits.user_id == user.id)).scalar_one_or_none()
        if credits:
            credits.msg_limit_base = 0
            credits.img_limit_base = 0
            credits.video_limit_base = 0
            print("Лимиты обнулены.")

        # 3. Удаляем запись о подписке (Subscription)
        sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
        if sub:
            db.delete(sub)
            print("Активная подписка удалена из базы.")

        db.commit()
        print(f"✅ Премиум успешно удален у пользователя {chat_id}.")

    except Exception as e:
        print(f"❌ Ошибка при удалении: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python remove_premium.py <chat_id>")
    else:
        try:
            chat_id_arg = int(sys.argv[1])
            remove_premium(chat_id_arg)
        except ValueError:
            print("❌ ID должен быть числом.")