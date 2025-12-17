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

    # Создаем таблицы если их нет
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"⚠️ Ошибка создания таблиц: {e}")

    db: Session = SessionLocal()
    
    try:
        print("🔄 [Catalog Sync] Обновление каталога в БД...")
        
        # Полная очистка таблиц перед загрузкой (чтобы удалить старое/ненужное)
        try:
            db.execute(text("TRUNCATE TABLE catalog_items RESTART IDENTITY CASCADE;"))
            db.execute(text("TRUNCATE TABLE catalog_pages RESTART IDENTITY CASCADE;"))
            db.execute(text("TRUNCATE TABLE catalog_categories RESTART IDENTITY CASCADE;"))
        except Exception:
            # Fallback если truncate не сработал
            db.query(CatalogItem).delete()
            db.query(CatalogPage).delete()
            db.query(CatalogCategory).delete()
        
        db.commit()

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
        print(f"✅ [Catalog Sync] Готово! Загружено элементов: {count_items}")

    except Exception as e:
        print(f"❌ [Catalog Sync] Ошибка: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    sync_db_from_json("catalog_data.json")