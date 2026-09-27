# Разработка

## Требования

| Инструмент | Версия | Зачем |
|---|---|---|
| **Docker + Compose** | актуальные | Полный стек (`docker compose up`), E2E. |
| **Python** | 3.13 (`>=3.13,<3.14`) | Backend. 3.14 пока не годится: нет колёс asyncpg/cryptography. |
| **Postgres** | 16 | Для тестов — либо compose, либо локальный. |
| **Node** | 22 (`>=22`) | Frontend. Vitest 4 требует 22+. |
| **uv** | опционально | Управление venv (в репозитории есть `uv.lock` окружения). |

## Полный стек (Docker)

```bash
cp .env.example .env
# отредактируй .env: JWT_SECRET_KEY, FERNET_KEY, POSTGRES_*
docker compose up -d --build
```

- SPA и API: `http://localhost`
- Swagger: `http://localhost/docs`
- Postgres опубликован на `127.0.0.1:${POSTGRES_PORT}` (только loopback).

Остановить: `docker compose down` (том `pgdata` сохраняется; `-v` его удалит).

## Локальный backend без Docker

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Postgres: подними только его из compose
docker compose up -d postgres

export DATABASE_URL="postgresql+asyncpg://felagi:change_me_in_prod@127.0.0.1:5432/felagi"
export JWT_SECRET_KEY="dev-local-secret"
alembic upgrade head          # применить миграции

uvicorn app.main:app --reload --port 8000
```

Воркер и планировщик — отдельными процессами:

```bash
python -m app.worker
python -m app.scheduler
```

> `JWT_SECRET_KEY` — обязательная настройка без дефолта: без неё приложение не
> стартует. `alembic` тоже читает настройки, поэтому переменную нужно задать и
> для миграций.

## Локальный frontend без Docker

```bash
cd frontend
npm ci
npm run dev        # Vite dev-сервер; /api проксируется на backend (см. vite.config.ts)
```

## Тесты

### Backend

```bash
cd backend
# Postgres-URL для тестов: отдельная БД (conftest делает drop_all/create_all!)
export TEST_DATABASE_URL="postgresql+asyncpg://felagi:change_me_in_prod@127.0.0.1:5432/felagi_test"
pytest -v
```

- **Без `TEST_DATABASE_URL`** тесты идут на SQLite in-memory, а всё, что помечено
  `@pytest.mark.postgres`, **пропускается** (`conftest.pytest_collection_modifyitems`).
  Postgres-маркер стоит там, где нужны реальные `SKIP LOCKED`, `pg_notify`,
  `LISTEN`, advisory-локи — на SQLite их нет.
- С `TEST_DATABASE_URL` запускается весь набор.
- **Никогда не направляйте `TEST_DATABASE_URL` на рабочую БД** — `conftest`
  сносит схему. Для этого в compose есть отдельная БД
  (`docker/postgres/init-test-db.sh`).

### Frontend

```bash
cd frontend
npx tsc --noEmit
npx vitest run
```

### E2E (Playwright)

```bash
cd frontend
npx playwright install --with-deps chromium   # один раз
npx playwright test
```

`playwright.config.ts` через `globalSetup` сам поднимает стек
(`docker compose up -d --build`) и ждёт `/healthz`. Чтобы не пересобирать
стек (если он уже поднят), выставьте `E2E_SKIP_SETUP=1`.

## Миграции Alembic

```bash
cd backend
export DATABASE_URL="postgresql+asyncpg://…"

alembic current                       # текущая ревизия
alembic upgrade head                  # применить все
alembic upgrade <revision>            # до конкретной
alembic downgrade -1                  # откатить одну
alembic downgrade base                # откатить всё
alembic revision -m "add x to y"      # новая пустая ревизия (заполнить вручную)
```

- Миграции — только явные (`op.add_column`/`create_table`), без автогенерации
  из моделей: контроль над DDL важнее удобства.
- Новую колонку `NOT NULL` на непустой таблице добавляйте с `server_default`,
  затем (при желании) снимайте дефолт отдельным `alter_column`.
- Миграции **не покрыты** в CI на SQLite — проверяйте upgrade **и** downgrade на
  реальном Postgres.

## Структура проекта

```
FELAGI-FLOW/
├── backend/
│   ├── app/
│   │   ├── api/routes/      # HTTP-роутеры (auth, workspaces, workflows, executions, hooks, ws …)
│   │   ├── api/ws_manager.py# LISTEN-менеджер для live-логов
│   │   ├── engine/          # runner, graph_validator, node_schemas, очередь, expressions
│   │   │   └── nodes/       # обработчики узлов (по одному на тип)
│   │   ├── scheduler/       # cron-планировщик (__main__.py)
│   │   ├── worker/          # worker-цикл (__main__.py)
│   │   ├── shared/          # модели, схемы, config, security, db
│   │   └── main.py          # FastAPI app + lifespan (LISTEN)
│   ├── alembic/versions/    # миграции
│   └── tests/               # pytest (postgres-маркер для БД-специфичных)
├── frontend/
│   └── src/
│       ├── api/             # REST-клиенты + WS-обёртка
│       ├── editor/          # React Flow: канвас, палитра, панель параметров, тулбар
│       ├── pages/           # WorkspaceList, WorkflowList, Editor, Executions, ExecutionDetail
│       ├── hooks/           # useExecutionLogs (WS + fallback)
│       ├── components/      # UI-kit + StatusBadge/JsonViewer/ConnectionIndicator
│       ├── stores/          # zustand (auth, editor)
│       ├── types/           # зеркала backend-схем
│       └── test-utils/      # мок WebSocket, renderHook
├── docker/postgres/         # init-скрипт тестовой БД
├── .github/workflows/       # CI
├── Caddyfile
└── docker-compose.yml
```

## Как добавить новый тип узла (5 шагов)

Тип узла — это запись в трёх местах: схема параметров, обработчик, и (для
триггеров/спец-валидации) правило валидатора. Палитра и валидация читают
`NODE_SCHEMAS`, поэтому дублировать метаданные не нужно.

**Шаг 1. Параметры узла** — `backend/app/engine/node_schemas.py`:

```python
class MyActionParams(BaseNodeParams):
    url: str
    retry_enabled: bool = True

NODE_SCHEMAS["action_myaction"] = NodeSchema(
    "My Action", "action", MyActionParams, ["default"],
)
```

`BaseNodeParams` уже даёт `retry` и `label`. JSON-Schema отсюда автоматически
попадёт в `GET /api/node-types` и в панель параметров фронтенда.

**Шаг 2. Обработчик** — `backend/app/engine/nodes/myaction.py`:

```python
async def handle_myaction(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    # context["nodes"][id]["output"] доступен как {{ nodes.<id>.output.* }}
    if not params.get("url"):
        return {"error": "url is required"}   # error → шаг failed
    return {"result": "..."}                  # output шага
```

Обработчики async (`handler(params, context) -> dict`). Верните `{"error": ...}`
для ошибки шага или `{"warning": ...}` для нефатального предупреждения —
runner разложит по статусу и `warnings`.

**Шаг 3. Регистрация** — `backend/app/engine/nodes/__init__.py`:

```python
from app.engine.nodes.myaction import handle_myaction
HANDLERS["action_myaction"] = handle_myaction
```

**Шаг 4. Валидация (если нужна).** Для особых правил (как у cron-выражения)
добавьте проверку в `graph_validator.validate_graph`. Для обычных типов ничего
не требуется: схема из шага 1 валидирует параметры сама.

**Шаг 5. Тесты.**

- `backend/tests/test_runner.py` — узел реально выполняется (output в шаге).
- `backend/tests/test_graph_validator.py` — принимает/отвергает параметры.
- Frontend-палитра подхватит узел автоматически по категории; отдельного кода
  для `action_*`/`transform_*` писать не нужно. Если для узла нужен особый
  виджет параметров — добавьте поле в `frontend/src/editor/ParamsPanel.tsx`.

Проверки перед коммитом:

```bash
cd backend && ruff check . && mypy . && pytest
cd frontend && npx tsc --noEmit && npx vitest run
```

## Стиль кода

- **Коммиты** — [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(scope): …`, `fix(scope): …`, `chore: …`. Сообщения на английском.
- **Backend** — ruff (`select = E,F,I,UP,B,SIM,RUF`) + mypy strict. `# type:
  ignore` не используется; для библиотек без типов — точечные
  `[[tool.mypy.overrides]]`.
- **Frontend** — TypeScript strict, без `@ts-ignore`.