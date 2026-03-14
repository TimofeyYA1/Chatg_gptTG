# FaceLab Bot

Telegram-бот и API для генерации/редактирования изображений на Gemini, с подписками, пакетами генераций, промокодами и учетом себестоимости генераций в USD.

## 1) Что в проекте

- `api_server/` — FastAPI backend (генерации, подписки, платежи, статистика, промо).
- `telegram_bot/` — Aiogram-бот (команды, UX, экраны, кнопки).
- `db_adapter/` — SQLAlchemy-модели, подключение к БД, миграции.
- `tools/` — служебные утилиты (проверка моделей, синк каталога с таблицами).
- `catalog_data.json` — контент каталога.
- `docker-compose.yml` — запуск полного стека (`db`, `api`, `bot`, `backup_service`).

## 2) Стек

- Python 3.11
- FastAPI + Uvicorn
- Aiogram 3
- SQLAlchemy + PostgreSQL
- Gemini API (`google-genai`)
- CloudPayments
- Docker Compose

## 3) Быстрый запуск через Docker

1. Создать `.env` из шаблона:

```bash
cp .env.example .env
```

2. Заполнить минимум:

- `TELEGRAM_BOT_TOKEN`
- `GEMINI_API_KEY`
- `POSTGRES_DSN`
- `INTERNAL_API_TOKEN`
- `CLOUDPAYMENTS_PUBLIC_ID`
- `CLOUDPAYMENTS_API_SECRET`

3. Поднять стек:

```bash
docker compose up -d --build
```

4. Проверить API:

```bash
curl http://127.0.0.1:8080/healthz
```

Ожидаемый ответ: `{"status":"ok"}`.

5. Проверить контейнеры:

```bash
docker compose ps
```

### 3.1) Развёртывание на VM (production)

1. Подготовить сервер (Ubuntu/Debian):

```bash
apt update
apt install -y git docker.io docker-compose-plugin
systemctl enable --now docker
```

2. Клонировать проект и перейти в каталог:

```bash
git clone <YOUR_REPO_URL> Chatg_gptTG
cd Chatg_gptTG
```

3. Создать `.env`:

```bash
cp .env.example .env
```

4. Обязательно заполнить в `.env`:

- `TELEGRAM_BOT_TOKEN` — токен бота.
- `GEMINI_API_KEY` — ключ Gemini.
- `POSTGRES_DSN` — строка подключения к БД.
- `INTERNAL_API_TOKEN` — внутренний токен API.
- `CLOUDPAYMENTS_PUBLIC_ID` и `CLOUDPAYMENTS_API_SECRET` — платежи.
- `API_PUBLIC_URL` и `PAYMENTS_PUBLIC_URL` — публичные URL проекта.
- `ADMIN_IDS` — список Telegram ID админов через запятую. Пример: `111111111,222222222`.
- `ADMIN_CHAT_ID` — один chat_id для уведомлений о платежах и получения бэкапов.

5. Запуск:

```bash
docker compose up -d --build
```

6. Проверка:

```bash
docker compose ps
curl http://127.0.0.1:8080/healthz
docker compose logs -f api
docker compose logs -f bot
```

7. Обновление на VM:

```bash
git pull
docker compose down --remove-orphans
docker compose up -d --build
```

## 4) Внутренний доступ API

- Внутренние роуты требуют заголовок:
  - `X-Internal-Token: <INTERNAL_API_TOKEN>`
- Публичные роуты без internal token:
  - `/healthz`
  - `/payments/checkout`
  - `/payments/webhook`

## 5) Команды бота (пользовательские)

- `/start` — главное меню.
- `/premium` — экран подписки.
- `/account` — экран аккаунта/подписки.
- `/packages` — докупка генераций (только при активной подписке).
- `/help` — справка.

## 6) Команды админа в Telegram

Источник: `telegram_bot/routers/mylook.py`.

| Команда           | Кто может                                                   | Назначение                                                                   | Формат                                              |
| ------------------------ | ------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `/set_menu`            | Сейчас доступна любому пользователю | Перезаписывает меню Telegram-команд бота                   | `/set_menu`                                             |
| `/update_prompts`      | `ADMIN_IDS`                                                       | Синк промптов из Google Sheet в БД                                    | `/update_prompts`                                       |
| `/gen`                 | `ADMIN_IDS`                                                       | Генерация промокодов (с бонусными генерациями) | `/gen [count] [generations=50] [max_uses=1]`            |
| `/promo_stats`         | `ADMIN_IDS`                                                       | Статистика промокодов + последние коды                | `/promo_stats`                                          |
| `/gen_track`           | `ADMIN_IDS`                                                       | Генерация трекинг-ссылок (без бонусов)                 | `/gen_track [count=1]`                                  |
| `/track_stats`         | `ADMIN_IDS`                                                       | Статистика трекинг-ссылок                                       | `/track_stats`                                          |
| `/export`              | `ADMIN_IDS`                                                       | Экспорт статистики пользователей в `.xlsx`            | `/export`                                               |
| `/give_subscription`   | `ADMIN_IDS`                                                       | Выдача подписки пользователю                                 | `/give_subscription <telegram_id> <days> <generations>` |
| `/add_subscription`    | `ADMIN_IDS`                                                       | Алиас `/give_subscription`                                                      | `/add_subscription <telegram_id> <days> <generations>`  |
| `/reset_subscription`  | `ADMIN_IDS`                                                       | Сброс/аннулирование подписки                                 | `/reset_subscription <telegram_id>`                     |
| `/cancel_subscription` | `ADMIN_IDS`                                                       | Алиас `/reset_subscription`                                                     | `/cancel_subscription <telegram_id>`                    |

### Примеры админ-команд в чате бота

```text
/gen
/gen 5 100 3
/gen_track 10
/give_subscription <CHAT_ID> 30 300
/reset_subscription <CHAT_ID>
/export
```

## 7) Админ-операции через Docker (без Telegram)

Все команды выполнять из корня проекта, где `docker-compose.yml`.

### 7.1 Выдать подписку вручную

```bash
docker compose exec api python give_premium.py <CHAT_ID> <start|pro|elite> [days]
```

Примеры:

```bash
docker compose exec api python give_premium.py <CHAT_ID> start 30
docker compose exec api python give_premium.py <CHAT_ID> pro 30
docker compose exec api python give_premium.py <CHAT_ID> elite 60
```

Что делает:

- создает/обновляет `subscriptions`
- ставит план (`Month_Std`, `Month_Std2`, `Month_Pro`)
- выставляет лимит генераций по плану
- отключает рекуррентный CloudPayments для этой ручной подписки (`cp_sub_id = None`)

### 7.2 Снять подписку

```bash
docker compose exec api python remove_premium.py <CHAT_ID>
```

Что делает:

- сбрасывает роль на `free`
- обнуляет базовые лимиты подписки
- удаляет запись из `subscriptions`

### 7.3 Полностью удалить пользователя

```bash
docker compose exec api python delete_user.py <CHAT_ID>
```

Либо расширенный сброс через утилиту:

```bash
docker compose exec api python tools/reset_user.py <CHAT_ID>
```

### 7.4 Посмотреть планы пользователей

```bash
docker compose exec api python get_plans.py
docker compose exec api python get_plans.py --active
```

## 8) Админ-операции через API (внутренние эндпоинты)

### 8.1 Выдать подписку через API

```bash
curl -X POST "http://127.0.0.1:8080/subscriptions/admin_give" \
  -H "X-Internal-Token: ${INTERNAL_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"chat_id":123456789,"days":30,"generations":300}'
```

### 8.2 Аннулировать подписку через API

```bash
curl -X POST "http://127.0.0.1:8080/subscriptions/admin_cancel" \
  -H "X-Internal-Token: ${INTERNAL_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"chat_id":123456789}'
```

### 8.3 Проверить статус подписки пользователя

```bash
curl "http://127.0.0.1:8080/subscriptions/summary/<CHAT_ID>" \
  -H "X-Internal-Token: ${INTERNAL_API_TOKEN}"
```

## 9) Gemini модели и проверка

Конфиг в `.env`:

- `NANOBANANA_MODEL_CHAT`
- `NANOBANANA_MODEL_CHAT_FALLBACK`
- `NANOBANANA_MODEL_IMAGE`
- `NANOBANANA_MODEL_IMAGE_PRO2`
- `NANOBANANA_MODEL_IMAGE_FALLBACK`

Проверка доступности моделей:

```bash
python tools/check_models.py
python tools/check_models.py --deep-image
```

## 10) Миграции и БД

- Автомиграции при старте API: `docker/entrypoint_api.sh` -> `python -m db_adapter.migrate`
- Ручной запуск миграций:

```bash
docker compose exec api python -m db_adapter.migrate
```

## 11) Каталог и контент

- `catalog_data.json` -> DB:

```bash
python sync_catalog.py
```

- Google Sheet -> JSON -> DB:

```bash
python tools/sync_from_sheet.py
```

- JSON -> Google Sheet:

```bash
python tools/export_to_sheet.py
```

## 12) Эксплуатация и диагностика

Проверить контейнеры:

```bash
docker compose ps
```

Логи API:

```bash
docker compose logs -f api
```

Логи бота:

```bash
docker compose logs -f bot
```

Перезапуск после обновления:

```bash
docker compose down --remove-orphans
docker compose up -d --build
```

## 13) Важные замечания

- `ADMIN_IDS` задаются через `.env` (пример в `.env.example`) и используются в боте и API.
- Команда `/set_menu` в текущем коде не ограничена `ADMIN_IDS`.
- Для внутренних API-операций нужен `INTERNAL_API_TOKEN`.
- Для реальных платежей обязательна корректная настройка CloudPayments webhook.

## 14) Резервное копирование (backup_service)

Как устроено сейчас:

- Контейнер: `backup_service` (см. `docker-compose.yml`).
- Скрипт: `backup_service/backup.py`.
- Расписание: каждый день в `07:00` по времени контейнера.
- Механика:

1. Делает `pg_dump` базы (`POSTGRES_DB`) с подключением к `DB_HOST`.
2. Сжимает дамп в `.sql.gz`.
3. Отправляет файл в Telegram через `sendDocument` на `ADMIN_CHAT_ID`.
4. Удаляет локальные временные файлы после отправки.

Какие переменные нужны:

- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_HOST`.
- `TELEGRAM_BOT_TOKEN`.
- `ADMIN_CHAT_ID`.

Важно:

- Если `TELEGRAM_BOT_TOKEN` или `ADMIN_CHAT_ID` пустые, файл в Telegram отправлен не будет.

Проверить, что сервис работает:

```bash
docker compose ps backup_service
docker compose logs -f backup_service
```

Запустить бэкап вручную прямо сейчас:

```bash
docker compose exec backup_service python -c "import backup; backup.create_backup()"
```

Восстановление из бэкапа:

1. Скачать `.sql.gz` из Telegram.
2. Распаковать локально: `gunzip backup_YYYY-MM-DD_HH-MM-SS.sql.gz`.
3. Восстановить в БД:

```bash
docker compose exec -T db psql -U postgres -d ai_superbot < backup_YYYY-MM-DD_HH-MM-SS.sql
```

Внимание: восстановление перезаписывает данные, делайте только на нужной среде.

## 15) Как работают ссылки в боте (промо и трекинг)

В проекте есть 2 типа ссылок:

- Промо-ссылки с бонусными генерациями.
- Трекинг-ссылки без бонусов (для аналитики каналов/источников).

### 15.1 Промо-ссылки (`/gen`)

Команда:

```text
/gen [count] [generations=50] [max_uses=1]
```

Пример:

```text
/gen 5 100 3
```

Что происходит:

1. Бот вызывает `POST /promo/generate`.
2. API генерирует токены (не начинаются с `trk_`).
3. Бот возвращает ссылки вида `https://t.me/<bot>?start=<token>`.
4. Пользователь открывает ссылку, срабатывает `/start`.
5. Бот вызывает `POST /promo/use`.
6. Если валидно, пользователю начисляются `image_credits`.

Ограничения по промо:

- Один и тот же пользователь не может активировать промо повторно.
- Если у пользователя уже есть подписка, промо не применяется.
- У токена есть лимит активаций `max_uses`.

Статистика промо в боте:

- Команда `/promo_stats`.
- Показывает:

1. Количество созданных кодов.
2. Количество активаций.
3. Уникальных пользователей.
4. Конверсию в подписку.
5. Последние коды и списки кто купил/не купил.

### 15.2 Трекинг-ссылки (`/gen_track`)

Команда:

```text
/gen_track [count=1]
```

Пример:

```text
/gen_track 10
```

Что происходит:

1. Бот вызывает `POST /promo/track/generate`.
2. API генерирует токены формата `trk_<...>`.
3. Бот отдает ссылки `https://t.me/<bot>?start=trk_<...>`.
4. При открытии `/start` бот вызывает `POST /promo/track/click`.
5. В БД пишется клик (`TrackLinkClick`), бонусы не выдаются.

Статистика трекинга в боте:

- Команда `/track_stats`.
- Показывает:

1. Всего создано трекинг-ссылок.
2. Всего кликов.
3. Уникальных пользователей.
4. Конверсию в подписку.
5. Детализацию по последним ссылкам.

Примечание по конверсии:

- Конверсия считается по пользователям, у которых в БД есть подписка на момент расчета статистики.

### 15.3 API для ссылок (если нужно смотреть вне Telegram)

Промо:

- `POST /promo/generate`
- `POST /promo/use`
- `GET /promo/list`
- `GET /promo/stats`

Трекинг:

- `POST /promo/track/generate`
- `POST /promo/track/click`
- `GET /promo/track/list`
- `GET /promo/track/stats`
