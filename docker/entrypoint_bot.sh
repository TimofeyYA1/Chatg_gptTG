#!/usr/bin/env bash
set -euo pipefail

# Убедимся, что код виден как пакет
export PYTHONPATH=/app

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [[ "$TELEGRAM_BOT_TOKEN" == 000000:* ]]; then
  echo "[bot] ERROR: TELEGRAM_BOT_TOKEN не задан (нужен токен, а не id)."
  exit 2
fi

echo "[bot] Waiting for API on http://api:8000/healthz …"
for i in {1..60}; do
  if curl -sf http://api:8000/healthz > /dev/null; then
    break
  fi
  sleep 1
done

echo "[bot] Starting polling…"
exec python -m telegram_bot.run_polling
