import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Настройки (путь к твоему JSON ключу от Google и имя файла каталога)
CREDENTIALS_FILE = 'credentials.json' # Твой файл ключей
SHEET_URL = 'https://docs.google.com/spreadsheets/d/1eZ-QQh90Kg0D47iQpR4Q5zRRbHS5VivaDtYwddlvq20/edit?gid=0#gid=0'
JSON_FILE = 'catalog_data.json'

def export_json_to_sheet():
    # 1. Подключаемся к Гуглу
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(SHEET_URL).sheet1

    # 2. Читаем текущий JSON
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 3. Преобразуем сложный JSON в плоскую таблицу
    rows = []
    # Заголовки
    rows.append(["slug", "gender", "type", "cat_title", "page", "slot", "item_title", "prompt", "is_premium", "image_path"])

    for cat in data:
        for page in cat['pages']:
            for item in page['items']:
                row = [
                    cat['slug'],
                    cat['gender'],
                    cat['type'],
                    cat['title_ru'],
                    page['page_number'],
                    item['slot'],
                    item['title'],
                    item['prompt'],       # <-- Промпт тут
                    item['is_premium'],
                    page['image_path']
                ]
                rows.append(row)

    # 4. Заливаем в таблицу
    sheet.clear()
    sheet.update(rows)
    print(f"✅ Успешно выгружено {len(rows)-1} строк в Google Таблицу!")

if __name__ == "__main__":
    export_json_to_sheet()