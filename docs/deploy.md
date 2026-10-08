# Деплой

Прод-конфигурация: **Render** (только api) -> **Neon** (managed Postgres) ->
**Vercel** (frontend) -> **cron-job.org** (keep-alive). Worker и scheduler на Render
не размещаются (background workers там платные) - они запускаются локально и
подключаются к той же Neon БД (см. §6). Локальная разработка - docker-compose.

```
браузер ─► Vercel (SPA) ──fetch/WS──► Render: felagi-flow-api ──┐
                                                                 ├──► Neon (Postgres)
        локальный ПК: worker x1 ──── LISTEN/NOTIFY/очередь ──────┘
        локальный ПК: scheduler x1 ── cron-тик ──────────────────┘
```

> Программа-минимум для проверки: можно поднять **только api** на Render и
> запускать вручную - но запуски будут висеть в `queued`, пока локально не
> поднят worker (§6).

## 0. Предусловия

- Аккаунты: Render, Neon, Vercel, cron-job.org (free-тарифов достаточно).
- Репозиторий на GitHub (Render и Vercel деплоят из него).
- Сгенерированные секреты:

  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # FERNET_KEY
  python -c "import secrets; print(secrets.token_urlsafe(48))"                               # JWT_SECRET_KEY
  ```

## 1. Neon (Postgres)

1. Создайте проект -> появится база `neondb` и пользователь.
2. В **Connection Details** выберите драйвер **SQLAlchemy/asyncpg** (или
   "Parameters only") и скопируйте строку. Она выглядит так:

   ```
   postgresql://<user>:<pass>@ep-xxx.<region>.aws.neon.tech/neondb?sslmode=require&channel_binding=require
   ```

3. **Ничего не правьте руками.** asyncpg не понимает `sslmode`/`channel_binding`
   (это libpq-синтаксис), но бэкенд сам приводит строку к нужному виду и включает
   TLS - см. `app/shared/db.py::normalize_database_url`:

   - `postgresql://` -> `postgresql+asyncpg://`;
   - `sslmode`/`channel_binding` вырезаются из query;
   - TLS (`connect_args={"ssl": "require"}`) включается, если `sslmode` был в
     строке, задан `DB_SSL_REQUIRE=true` или хост оканчивается на `.neon.tech`.

   Ту же нормализацию повторяет LISTEN-соединение для live-логов
   (`app/api/ws_manager.py`), иначе WS-канал не поднялся бы.

4. Миграции. Neon-строку нужно прогнать через Alembic **до** старта сервисов
   (локально или из Render Shell):

   ```bash
   cd backend
   export DATABASE_URL="<строка из Neon>"
   export JWT_SECRET_KEY="<любое значение для запуска settings>"
   alembic upgrade head
   ```

   В Blueprint миграции намеренно не автоматизированы - их прогоняем вручную
   один раз перед стартом. Для автоматизации на будущих планах подойдёт
   `preDeployCommand` (Render) или отдельный one-off job.

## 2. Render (Blueprint)

1. В Dashboard: **New -> Blueprint**, подключите репозиторий. Render найдёт
   `render.yaml` в корне.
2. Blueprint создаст **один** сервис из образа `backend/Dockerfile`:

   | Сервис | Тип | Команда |
   |---|---|---|
   | `felagi-flow-api` | web | CMD из Dockerfile: `uvicorn ... --port ${PORT:-8000}` |

   > `plan: free` - бесплатный инстанс. Free-сервисы Render засыпают после ~15
   > минут простоя и "просыпаются" при следующем запросе; чтобы этого не было -
   > cron-job.org (§4).
   >
   > **У api `dockerCommand` намеренно не задан** - он стартует по `CMD` из
   > `backend/Dockerfile`, который слушает `${PORT:-8000}` (shell-форма CMD
   > раскрывает переменную стандартным механизмом Docker). Render задаёт `PORT`
   > (по умолчанию 10000) - api слушает его.
   >
   > Worker и scheduler здесь **отсутствуют**: на Render background workers
   > требуют платный план. Они запускаются локально - см. §6.

3. При создании Render спросит значения для переменных с `sync: false`
   (группа `felagi-flow-secrets`). Заполните:

   | Переменная | Значение |
   |---|---|
   | `DATABASE_URL` | строка Neon (как есть, см. §1) |
   | `JWT_SECRET_KEY` | сгенерированный секрет |
   | `FERNET_KEY` | сгенерированный ключ |
   | `LLM_API_KEY` | ключ OpenAI-совместимого API |
   | `FRONTEND_URL` | домен Vercel (заполнить после §3), напр. `https://app.vercel.app` |
   | `CORS_ORIGINS` | `["https://app.vercel.app"]` (тот же домен) |

   Остальные (`LLM_BASE_URL`, `LLM_MODELS`, `COOKIE_SECURE=true`,
   `COOKIE_SAMESITE=none`, `LOG_LEVEL`) заданы в Blueprint.

4. После первого деплоя возьмите публичный URL api:
   `https://felagi-flow-api.onrender.com` - он нужен фронтенду (§3).

### Почему COOKIE_SAMESITE=none

Refresh-cookie ходит между `*.vercel.app` и `*.onrender.com` - это **разные
сайты**, и браузер не отправит `SameSite=Lax` cookie в таком запросе. Поэтому в
проде `COOKIE_SAMESITE=none` и обязательный `COOKIE_SECURE=true` (то есть только
по HTTPS). Локально (один домен, один Caddy) остаётся `lax`.

### WebSocket на Render

`/ws/*` на Render можно подключать напрямую: он поддерживает WebSocket на web
сервисах. Отдельный прокси не нужен - фронтенд идёт на тот же хост api (§3).

## 3. Vercel (frontend)

1. **New Project** -> репозиторий -> Root Directory: `frontend`.
2. Framework preset: **Vite**. Build: `npm run build`, Output: `dist`.
3. Environment Variables (Production):

   | Переменная | Значение |
   |---|---|
   | `VITE_API_URL` | `https://felagi-flow-api.onrender.com` |

   `VITE_*` вшиваются в бандл на этапе сборки - после изменения нужен redeploy.

4. Задеплойте и скопируйте домен (`https://<project>.vercel.app`) в Render
   (`FRONTEND_URL` и `CORS_ORIGINS` в §2.3), затем передеплойте api.

### Как фронтенд находит api

- `VITE_API_URL` пуст -> запросы идут на origin страницы (локально, где фронт и
  api отдаёт один Caddy).
- `VITE_API_URL` задан -> REST идёт на этот хост (`frontend/src/api/client.ts`),
  а WebSocket - на тот же хост со схемой `wss://`
  (`frontend/src/api/ws.ts`).

## 4. cron-job.org (keep-alive)

Free-инстансы Render засыпают после ~15 минут без трафика. Чтобы api не "просыпался"
на первом запросе:

1. Создайте cronjob в [cron-job.org](https://cron-job.org/) на URL
   `https://felagi-flow-api.onrender.com/healthz` с интервалом 5 минут.
2. Метод - `GET`, ожидайте ответ `200` и статус `ok` в теле.

Пингуйте **только api**. Worker и scheduler - не на Render, у них нет публичного
URL (§6); их пробуждает не внешний пинг, а работа с БД.

## 5. Проверка после деплоя

```bash
# api жив и поднял схему
curl -fsS https://felagi-flow-api.onrender.com/healthz
# -> {"status":"ok"}

# фронт открывается, регистрация работает, live-логи идут (WS)
# откройте https://<project>.vercel.app, зарегистрируйтесь, запустите workflow
```

Порядок диагностики, если что-то не так:

| Симптом | Проверить |
|---|---|
| api не стартует, ошибка SSL к БД | `DATABASE_URL` - строка Neon целиком, с `sslmode`; TLS включается автоматически |
| CORS-ошибка в браузере | `CORS_ORIGINS` = точный origin Vercel (со схемой, без слэша) |
| Не логинится / "пропадает" сессия | `COOKIE_SAMESITE=none` **и** `COOKIE_SECURE=true`, оба на api |
| Live-логи не идут, обычные запросы ок | WS на тот же хост, что REST; проверьте `wss://` и `CORS_ORIGINS` |
| Запуски висят в `queued` | worker не запущен локально (§6) или не видит Neon |

## 6. Worker и Scheduler - локально

API работает на Render Free. Worker и Scheduler запускаются на локальном ПК и
подключаются к **той же Neon БД**, что и API.

### Зачем

- **Worker** выполняет задачи из очереди (`executions`).
- **Scheduler** создаёт `executions` по cron-расписанию.

Без них: ручной запуск создаёт execution в `queued`, но никто его не выполняет.
Cron не срабатывает.

### Как запустить

1. Скопировать пример конфигурации в рабочий `.env`:

   ```bash
   cp .env.prod.example .env
   ```

2. Указать `DATABASE_URL` от Neon - **тот же**, что задан на Render (§2.3), и те
   же секреты (`JWT_SECRET_KEY`, `FERNET_KEY`, `LLM_API_KEY`, `LLM_*`). Строку
   Neon можно вставлять как есть, с `sslmode=require` - бэкенд нормализует её сам
   (§1.3).

3. Поднять worker и scheduler:

   ```bash
   docker compose up -d worker scheduler
   ```

   `postgres` не поднимется: у сервисов `worker` и `scheduler` нет `depends_on`,
   и compose запускает только запрошенные сервисы. `api` и `caddy` тоже не
   стартуют - они не нужны и работают на Render. **Важно:** подстановка
   переменных в `docker-compose.yml` идёт по всему файлу, поэтому `POSTGRES_*` и
   `DATABASE_URL` должны быть заданы (в `.env.prod.example` они уже есть) - иначе
   `docker compose` завершится ошибкой ещё до запуска.

4. Проверить, что воркер стартовал:

   ```bash
   docker compose logs worker
   # -> {"event": "worker.started", "worker_id": "worker-...", ...}
   ```

   С этого момента запуски, созданные на Render-инстансе api, будут
   выполняться локальным worker'ом (оба видят одну Neon-очередь через
   `FOR UPDATE SKIP LOCKED`).

### Ограничения

- Worker работает только пока ПК включён. Пока он выключен, запуски копятся в
  `queued` и выполняются после запуска (`reclaim` вернёт и "зависшие").
- Для 24/7 нужен VPS или платные background workers на Render (см. §Стоимость).
- Останавливать: `docker compose stop worker scheduler` (или `down`, но `down -v`
  удалит локальный том `pgdata`).

## Обновление секретов

`sync: false` Render подставляет **только при первичном создании** Blueprint.
Позже менять значения - вручную: Dashboard -> сервис/группа -> Environment.

## Стоимость и альтернативы для 24/7

Текущая схема - полностью на бесплатных тарифах:

- **Render Free** - api (засыпает без трафика; будит cron-job.org).
- **Neon Free**, **Vercel Free**, **cron-job.org Free**.
- **Worker + scheduler** - на локальном ПК (бесплатно, но только пока ПК включён).

Если нужен режим 24/7, worker и scheduler должны работать постоянно. Два пути:

1. **Render Background Workers** - добавить в `render.yaml` два сервиса `type:
   worker` (команды `python -m app.worker` и `python -m app.scheduler`) - но они
   платные (от ~$7/мес за каждый). Тогда `dockerCommand`-поле обязательно; api
   остаётся как есть.
2. **VPS** - поставить docker-compose (или только `python -m app.worker`/
   `python -m app.scheduler`) на недорогой VPS и направить `DATABASE_URL` на ту
   же Neon-БД. Для этого можно переиспользовать `.env.prod.example` и поднять
   там те же сервисы: `docker compose up -d worker scheduler`.

В обоих случаях БД одна (Neon) - api на Render, worker/scheduler где угодно,
связь через общую очередь в Postgres.