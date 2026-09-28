FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-cache-dir -e . \
    && useradd --create-home --uid 10001 appuser

USER appuser

EXPOSE 8000

# Shell-форма (не exec): нужна подстановка ${PORT}. На Render web-сервис
# слушает $PORT (по умолчанию 10000), локально порт берётся из EXPOSE-дефолта
# 8000. docker-compose переопределяет CMD своим `command`, поэтому локально
# поведение не меняется.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
