import json
import gspread
import os
import sys
from oauth2client.service_account import ServiceAccountCredentials

# --- ВЫЧИСЛЯЕМ ПУТИ ---
# Получаем абсолютный путь к папке tools
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# Получаем путь к корню проекта (на уровень выше tools)
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

# Добавляем корень в sys.path, чтобы импортировать sync_catalog
sys.path.append(PROJECT_ROOT)
from sync_catalog import sync_db_from_json

# Файлы лежат в корне
CREDENTIALS_FILE = os.path.join(PROJECT_ROOT, 'credentials.json')
SHEET_URL = 'https://docs.google.com/spreadsheets/d/1eZ-QQh90Kg0D47iQpR4Q5zRRbHS5VivaDtYwddlvq20/edit?gid=0#gid=0' # <--- ВСТАВЬ СВОЮ ССЫЛКУ!!!
OUTPUT_JSON = os.path.join(PROJECT_ROOT, 'catalog_data.json')

def str_to_bool(s):
    return str(s).lower() in ('true', '1', 'yes')

def sync_sheet_to_db():
    print("⏳ [Sync Sheet] Старт...")
    print(f"📂 Корень проекта: {PROJECT_ROOT}")
    
    # Проверка наличия ключей
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"❌ Ошибка: Не найден файл {CREDENTIALS_FILE}")
        print("Положите credentials.json в корень проекта!")
        return

    # 1. Подключение
    print("☁️ Подключаюсь к Google...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    
    try:
        sheet = client.open_by_url(SHEET_URL).sheet1
    except Exception as e:
        print(f"❌ Ошибка доступа к таблице: {e}")
        return
    
    # Получаем данные
    records = sheet.get_all_records()
    print(f"📥 Скачано {len(records)} строк.")
    
    # 2. Сборка JSON
    catalog_map = {} 

    for row in records:
        # Пропускаем пустые строки
        if not row.get('slug'): continue

        cat_key = (row['slug'], row['gender'])
        
        if cat_key not in catalog_map:
            catalog_map[cat_key] = {
                "slug": row['slug'],
                "type": row['type'],
                "gender": row['gender'],
                "title_ru": row['cat_title'],
                "pages": [] 
            }
        
        category = catalog_map[cat_key]
        
        # Страница
        page_num = row['page']
        target_page = None
        for p in category['pages']:
            if p['page_number'] == page_num:
                target_page = p
                break
        
        if not target_page:
            target_page = {
                "page_number": page_num,
                "image_path": row['image_path'],
                "items": []
            }
            category['pages'].append(target_page)
        
        # Элемент
        item = {
            "slot": row['slot'],
            "title": row['item_title'],
            "prompt": row['prompt'],
            "is_premium": str_to_bool(row['is_premium'])
        }
        target_page['items'].append(item)

    final_json_data = list(catalog_map.values())

    # 3. Сохраняем в корень
    try:
        with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
            json.dump(final_json_data, f, ensure_ascii=False, indent=2)
        print(f"✅ Файл обновлен: {OUTPUT_JSON}")
    except Exception as e:
        print(f"❌ Ошибка записи JSON: {e}")
        return

    # 4. Обновляем БД
    print("🔄 Запускаю обновление БД...")
    sync_db_from_json(OUTPUT_JSON)

if __name__ == "__main__":
    sync_sheet_to_db()