FROM python:3.11-slim

# Устанавливаем клиент PostgreSQL (нужен для pg_dump)
RUN apt-get update && apt-get install -y postgresql-client && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Устанавливаем библиотеки для Python
RUN pip install requests schedule

# Копируем скрипт
COPY backup.py .

CMD ["python", "backup.py"]