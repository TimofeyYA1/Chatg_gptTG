
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends     build-essential curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN printf '#!/usr/bin/env bash\nset -e\ncurl -sf http://localhost:8000/healthz > /dev/null\n' > /healthcheck.sh && chmod +x /healthcheck.sh

CMD ["bash", "-lc", "uvicorn api_server.main:app --host 0.0.0.0 --port 8000"]
