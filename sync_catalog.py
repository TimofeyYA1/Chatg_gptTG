import json
import os
import sys

# Добавляем текущую директорию в путь
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from sqlalchemy.orm import Session
from db_adapter.database import SessionLocal, engine, Base
from db_adapter.models import CatalogCategory, CatalogPage, CatalogItem

def sync_db_from_json(json_file: str):
    if not os.path.exists(json_file):
        print(f"⏩ Файл {json_file} не найден. Пропуск синхронизации.")
        return

    # Читаем файл с авто-определением кодировки
    data = None
    encodings = ['utf-8', 'utf-8-sig', 'cp1251']
    for enc in encodings:
        try:
            with open(json_file, "r", encoding=enc) as f:
                data = json.load(f)
            break
        except Exception:
            continue
    
    if data is None:
        print("❌ Ошибка: Не удалось прочитать JSON.")
        return

    print("🔄 [Catalog Sync] Пересоздание таблиц каталога...")
    
    # 1. Жестко удаляем старые таблицы, чтобы сбросить схему (indexes/constraints)
    try:
        with engine.connect() as conn:
            # Удаляем таблицы в обратном порядке зависимости
            conn.execute(text("DROP TABLE IF EXISTS catalog_items CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS catalog_pages CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS catalog_categories CASCADE"))
            conn.commit() # ВАЖНО: Фиксируем удаление
            print("✅ Старые таблицы удалены.")
    except Exception as e:
        print(f"⚠️ Ошибка при удалении таблиц: {e}")

    # 2. Создаем таблицы заново с новой схемой
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ Новые таблицы созданы.")
    except Exception as e:
        print(f"⚠️ Ошибка создания таблиц: {e}")
        return

    db: Session = SessionLocal()
    
    try:
        print("📥 [Catalog Sync] Загрузка данных...")
        
        count_items = 0
        for cat_data in data:
            category = CatalogCategory(
                slug=cat_data["slug"],
                type=cat_data["type"],
                gender=cat_data["gender"],
                title_ru=cat_data["title_ru"]
            )
            db.add(category)
            db.flush()

            for page_data in cat_data["pages"]:
                page = CatalogPage(
                    category_id=category.id, 
                    page_number=page_data["page_number"],
                    image_path=page_data["image_path"]
                )
                db.add(page)
                db.flush()

                for item_data in page_data["items"]:
                    item = CatalogItem(
                        page_id=page.id,
                        slot_number=item_data["slot"],
                        title=item_data["title"],
                        prompt=item_data["prompt"],
                        is_premium=item_data.get("is_premium", True)
                    )
                    db.add(item)
                    count_items += 1
        
        db.commit()
        print(f"✅ [Catalog Sync] Успешно! Загружено элементов: {count_items}")

    except Exception as e:
        print(f"❌ [Catalog Sync] Ошибка транзакции: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    sync_db_from_json("catalog_data.json")