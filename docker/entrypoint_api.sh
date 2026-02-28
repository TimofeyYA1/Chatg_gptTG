#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH=/app

echo "[api] Waiting for Postgres at ${POSTGRES_DSN}…"
python - <<'PY'
import os, time, sys
from sqlalchemy import create_engine, text
dsn=os.environ["POSTGRES_DSN"]
for i in range(60):
    try:
        create_engine(dsn).connect().execute(text("SELECT 1"))
        print("DB is up"); break
    except Exception:
        time.sleep(1)
else:
    print("DB not reachable", file=sys.stderr); sys.exit(1)
PY

echo "[api] Creating tables if not exist…"
python -m db_adapter.create_tables || true

echo "[api] Running DB migrations..."
python -m db_adapter.migrate

echo "[api] Syncing catalog from JSON..."
python sync_catalog.py

echo "[api] Starting Uvicorn…"
exec uvicorn api_server.main:app --host 0.0.0.0 --port 8000 --no-server-header
