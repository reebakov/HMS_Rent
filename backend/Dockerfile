FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# версия сборки (sha коммита): CI передаёт её build-arg'ом, /api/health отдаёт её интерфейсу
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

EXPOSE 8000

# Миграции применяются при каждом старте (идемпотентно), затем поднимается API. exec: uvicorn становится PID 1 и получает
# SIGTERM от docker stop; иначе sh его глотает, остановка (выкатка) ждёт 10 с и убивает backend вместе с запросами
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
