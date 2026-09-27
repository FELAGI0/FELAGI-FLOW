# Felagi Flow

Платформа визуальной автоматизации с AI-узлами: self-hosted, developer-first.

Собирайте workflow как граф — триггеры, действия, логика — и запускайте их
вручную, по расписанию или по вебхуку, наблюдая за выполнением в реальном
времени.

## Что умеет

- **Визуальный редактор графа** (React Flow): триггеры → действия, ветвление If.
- **Триггеры**: ручной запуск, cron-расписание, публичный вебхук.
- **Действия**: HTTP Request, LLM (OpenAI-совместимый API), Set, If, Debug.
- **Live-логи выполнения** через WebSocket (LISTEN/NOTIFY fan-out).
- **Retry-политики per-node** (`max_retries`, `backoff`: fixed/exponential).
- **Мультитенантность**: workspaces, роли (owner/admin/member), приглашения.
- **История запусков** с фильтрами по workflow/статусу и keyset-пагинацией.

> Узлов ровно восемь (три триггера + пять действий/логики). Telegram, Gmail,
> Notion, Sheets, Discord и poll-триггеры — в планах (см. `DESIGN.md`, этапы 6+);
> в текущем коде их нет.

## Стек

**Backend:** Python 3.13, FastAPI, SQLAlchemy 2.0 (async), Alembic,
PostgreSQL 16, asyncpg, croniter, `openai` SDK, PyJWT, argon2.

**Frontend:** React 19, TypeScript 5.9, Vite 7, React Flow 12, TanStack Query,
Zustand, Tailwind 4.

**Инфра:** Docker, docker-compose, Caddy.

## Архитектура (краткая)

```
                    ┌──────────────────────────────┐
  браузер  ───────► │ Caddy (:80)                  │
                    │  /api/*, /hooks/*, /ws/*     │──► API (FastAPI)
                    │  static /  → SPA             │
                    └──────────────────────────────┘         │
                                                             ▼
                                              ┌──────────────────────────┐
                                              │ PostgreSQL 16            │
                                              │  данные + очередь         │
                                              │  LISTEN/NOTIFY (exec_log) │
                                              └──────────────────────────┘
                                                 ▲        ▲          ▲
                                                 │        │          │
                              Worker ×N ─────────┘        │          └─── Scheduler ×1
                              (claim + run)               │              (cron, tick 15s)
                                    │                     │
                                    ▼                     │
                       внешние API (LLM, HTTP)           │
                                                          │
                       API держит LISTEN ─────────────────┘
                       → fan-out в WebSocket-соединения
```

- **Очередь на Postgres:** `executions` — одновременно журнал и рабочая
  очередь. Забор задач через `FOR UPDATE SKIP LOCKED`, продление владения
  через heartbeat, reclaim зависших.
- **Live-логи:** runner шлёт `NOTIFY exec_log, <execution_id>` в той же
  транзакции, что и запись шага. Каждая реплика API держит `LISTEN` и
  рассылает уведомление в свои WebSocket-соединения.
- **Планировщик:** один инстанс (cluster-wide `pg_try_advisory_lock`), раз в
  15 секунд забирает созревшие расписания.

Подробнее — [`docs/architecture.md`](docs/architecture.md).

## Быстрый старт

```bash
git clone https://github.com/FELAGI0/FELAGI-FLOW.git
cd FELAGI-FLOW
cp .env.example .env
# отредактируй .env: JWT_SECRET_KEY, FERNET_KEY, POSTGRES_* (см. комментарии в файле)
docker compose up -d --build
# открой http://localhost
```

Стек: `postgres`, `api`, `worker`, `scheduler`, `caddy`. Проверка готовности —
`http://localhost/healthz`.

## Разработка

Требования, локальный запуск без Docker, миграции, структура проекта и
пошаговая инструкция «как добавить новый тип узла» — в
[`docs/development.md`](docs/development.md).

## API

Swagger UI: `http://localhost/docs`, OpenAPI: `http://localhost/openapi.json`.
Обзор основных эндпоинтов с примерами — [`docs/api.md`](docs/api.md).

## Тесты

```bash
# backend (нужен Postgres: часть тестов помечена @pytest.mark.postgres)
cd backend
export TEST_DATABASE_URL="postgresql+asyncpg://felagi:change_me_in_prod@127.0.0.1:5432/felagi_test"
pytest -v

# frontend
cd frontend
npx vitest run

# E2E (поднимает стек через docker compose)
npx playwright test
```

## Скриншоты

<!-- Положить файлы в docs/images/ и раскомментировать: -->

<!-- ![Редактор графа](docs/images/editor.png) -->
<!-- ![Детали запуска с live-логами](docs/images/execution-live.png) -->

Раздел зарезервирован: изображения ещё не добавлены в репозиторий.

## Лицензия

MIT.