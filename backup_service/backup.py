import os
import time
import subprocess
import requests
import schedule
from datetime import datetime
import gzip
import stat

# Функция для получения переменной с защитой от пустых строк
def get_env(key, default):
    value = os.getenv(key)
    if not value or value.strip() == "":
        return default
    return value

# Настройки
DB_HOST = get_env("DB_HOST", "db")
DB_NAME = get_env("POSTGRES_DB", "ai_superbot")
DB_USER = get_env("POSTGRES_USER", "postgres")
DB_PASS = get_env("POSTGRES_PASSWORD", "postgres")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

def create_backup():
    print(f"⏳ Начинаю бекап...")
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"backup_{timestamp}.sql"
    gz_filename = f"{filename}.gz"
    pgpass_file = "pgpass_tmp"

    # 1. Создаем файл .pgpass
    try:
        with open(pgpass_file, "w") as f:
            f.write(f"{DB_HOST}:5432:{DB_NAME}:{DB_USER}:{DB_PASS}")
        os.chmod(pgpass_file, stat.S_IRUSR | stat.S_IWUSR)
    except Exception as e:
        print(f"❌ Ошибка создания pgpass: {e}")
        return

    env = os.environ.copy()
    env["PGPASSFILE"] = os.path.abspath(pgpass_file)

    cmd = [
        "pg_dump",
        "-h", DB_HOST,
        "-U", DB_USER,
        "-d", DB_NAME,
        "-f", filename
    ]

    try:
        subprocess.run(cmd, env=env, check=True)
        print("✅ Дамп успешно создан.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка pg_dump: {e}")
        send_telegram_message(f"❌ Ошибка бекапа: Не удалось создать дамп.")
        if os.path.exists(pgpass_file): os.remove(pgpass_file)
        return

    if os.path.exists(pgpass_file):
        os.remove(pgpass_file)

    # 2. Сжимаем
    try:
        with open(filename, 'rb') as f_in:
            with gzip.open(gz_filename, 'wb') as f_out:
                import shutil
                shutil.copyfileobj(f_in, f_out)
        
        os.remove(filename)
        print(f"✅ Сжат: {gz_filename}")
        
        # 3. Отправляем
        send_telegram_file(gz_filename)
        
    except Exception as e:
        print(f"❌ Ошибка обработки файла: {e}")
    finally:
        if os.path.exists(gz_filename):
            os.remove(gz_filename)

def send_telegram_message(text):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
                      json={"chat_id": ADMIN_CHAT_ID, "text": text})
    except: pass

def send_telegram_file(filepath):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        with open(filepath, 'rb') as f:
            files = {'document': f}
            caption = f"📦 Ежедневный бекап {datetime.now().strftime('%d.%m.%Y')}\nDB: {DB_NAME}"
            data = {'chat_id': ADMIN_CHAT_ID, 'caption': caption}
            
            res = requests.post(url, data=data, files=files)
            if res.status_code == 200:
                print("🚀 Успешно отправлено!")
            else:
                print(f"❌ Ошибка Telegram: {res.text}")
    except Exception as e:
        print(f"❌ Ошибка сети: {e}")

if __name__ == "__main__":
    print("🤖 Сервис бекапов запущен. Расписание: ежедневно в 07:00.")
    print(f"🔧 Конфигурация: DB_HOST={DB_HOST}, DB_NAME={DB_NAME}")
    
    # Расписание: раз в день в 07:00
    schedule.every().day.at("07:00").do(create_backup)

    while True:
        schedule.run_pending()
        time.sleep(60)