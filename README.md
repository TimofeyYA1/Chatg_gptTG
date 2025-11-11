
# AI SuperBot — минимальный стек (PostgreSQL + FastAPI + aiogram)

**Что входит:** одна БД (PostgreSQL), один API (FastAPI) и Telegram-бот (aiogram 3). Без Redis/MinIO.

## Запуск (Docker)
1) `cp .env.example .env` и укажи `TELEGRAM_BOT_TOKEN` и `OPENAI_API_KEY`.
2) `docker compose up --build`
3) Проверка:
   - API: http://localhost:8080/healthz
   - Бот: в Telegram отправь `/start`

## Структура
```
db_adapter/        # SQLAlchemy, модели и создание таблиц
api_server/        # FastAPI, роутеры, адаптер OpenAI (чат + GPT-Image-1)
telegram_bot/      # aiogram 3, /start, /account, /image
common/            # конфиг, логирование
```

## Примечания
- Вебхук уже предусмотрен: `POST /bot/webhook`. По умолчанию используется polling для простого запуска.
- Онбординг: начисляется 15 премиум-запросов при первом заходе `/start`.
