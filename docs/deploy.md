# Деплой

Прод-конфигурация: **Render** (backend: api + worker + scheduler) → **Neon**
(managed Postgres) → **Vercel** (frontend) → **UptimeRobot** (keep-alive).
Локальная разработка остаётся на docker-compose — он для деплоя не используется.

```
браузер ─► Vercel (SPA) ──fetch/WS──► Render: felagi-flow-api ─┐
                                           ▲                    │
                     Render: worker ×1 ────┤  LISTEN/NOTIFY     ├──► Neon (Postgres)
                     Render: scheduler ×1 ─┘                    │
```

## 0. Предусловия

- Аккаунты: Render, Neon, Vercel, UptimeRobot (free-тарифов достаточно).
- Репозиторий на GitHub (Render и Vercel деплоят из него).
- Сгенерированные секреты:

  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # FERNET_KEY
  python -c "import secrets; print(secrets.token_urlsafe(48))"                               # JWT_SECRET_KEY
  ```

## 1. Neon (Postgres)

1. Создайте проект → появится база `neondb` и пользователь.
2. В **Connection Details** выберите драйвер **SQLAlchemy/asyncpg** (или
   «Parameters only») и скопируйте строку. Она выглядит так:

   ```
   postgresql://<user>:<pass>@ep-xxx.<region>.aws.neon.tech/neondb?sslmode=require&channel_binding=require
   ```

3. **Ничего не правьте руками.** asyncpg не понимает `sslmode`/`channel_binding`
   (это libpq-синтаксис), но бэкенд сам приводит строку к нужному виду и включает
   TLS — см. `app/shared/db.py::normalize_database_url`:

   - `postgresql://` → `postgresql+asyncpg://`;
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

   В Blueprint миграции намеренно не автоматизированы — запускать их из
   `startCommand` рискованно (несколько сервисов стартуют параллельно и могли бы
   гнать `upgrade` одновременно). Для автоматизации используйте
   `preDeployCommand` (Render) или отдельный one-off job.

## 2. Render (Blueprint)

1. В Dashboard: **New → Blueprint**, подключите репозиторий. Render найдёт
   `render.yaml` в корне.
2. Blueprint создаст три сервиса из одного образа `backend/Dockerfile`:

   | Сервис | Тип | Команда |
   |---|---|---|
   | `felagi-flow-api` | web | CMD из Dockerfile: `uvicorn … --port ${PORT:-8000}` |
   | `felagi-flow-worker` | worker | `python -m app.worker` |
   | `felagi-flow-scheduler` | worker | `python -m app.scheduler` |

   > Для сервисов с `runtime: docker` команда задаётся полем `dockerCommand`
   > (в Dashboard — «Docker Command»). Поле `startCommand` относится к нативным
   > рантаймам и для docker игнорируется.
   >
   > **У api `dockerCommand` намеренно не задан** — он стартует по `CMD` из
   > `backend/Dockerfile`, который слушает `${PORT:-8000}` (shell-форма CMD
   > раскрывает переменную стандартным механизмом Docker). Так мы не зависим от
   > того, подставляет ли Render `$PORT` внутри `dockerCommand`, и не дублируем
   > команду. Render задаёт `PORT` (по умолчанию 10000) — api слушает его.
   > У worker/scheduler `dockerCommand` указан: их команды не требуют переменных.

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
   `https://felagi-flow-api.onrender.com` — он нужен фронтенду (§3).

### Почему COOKIE_SAMESITE=none

Refresh-cookie ходит между `*.vercel.app` и `*.onrender.com` — это **разные
сайты**, и браузер не отправит `SameSite=Lax` cookie в таком запросе. Поэтому в
проде `COOKIE_SAMESITE=none` и обязательный `COOKIE_SECURE=true` (то есть только
по HTTPS). Локально (один домен, один Caddy) остаётся `lax`.

### WebSocket на Render

`/ws/*` на Render можно подключать напрямую: он поддерживает WebSocket на web
сервисах. Отдельный прокси не нужен — фронтенд идёт на тот же хост api (§3).

## 3. Vercel (frontend)

1. **New Project** → репозиторий → Root Directory: `frontend`.
2. Framework preset: **Vite**. Build: `npm run build`, Output: `dist`.
3. Environment Variables (Production):

   | Переменная | Значение |
   |---|---|
   | `VITE_API_URL` | `https://felagi-flow-api.onrender.com` |

   `VITE_*` вшиваются в бандл на этапе сборки — после изменения нужен redeploy.

4. Задеплойте и скопируйте домен (`https://<project>.vercel.app`) в Render
   (`FRONTEND_URL` и `CORS_ORIGINS` в §2.3), затем передеплойте api.

### Как фронтенд находит api

- `VITE_API_URL` пуст → запросы идут на origin страницы (локально, где фронт и
  api отдаёт один Caddy).
- `VITE_API_URL` задан → REST идёт на этот хост (`frontend/src/api/client.ts`),
  а WebSocket — на тот же хост со схемой `wss://`
  (`frontend/src/api/ws.ts`).

## 4. UptimeRobot (keep-alive)

Free-инстансы Render засыпают после ~15 минут без трафика. Чтобы api не «просыпался»
на первом запросе:

1. Добавьте HTTP(s)-монитор: `https://felagi-flow-api.onrender.com/healthz`,
   интервал 5 минут.
2. Тип — HTTP(s), ожидаемый ответ `200` и статус `ok` в теле.

Пингуйте **только api**. Worker и scheduler — background workers, у них нет
публичного URL; их должен будить трафик в БД (worker опрашивает очередь, scheduler
тикает по расписанию), а не внешний пинг.

## 5. Проверка после деплоя

```bash
# api жив и поднял схему
curl -fsS https://felagi-flow-api.onrender.com/healthz
# → {"status":"ok"}

# фронт открывается, регистрация работает, live-логи идут (WS)
# откройте https://<project>.vercel.app, зарегистрируйтесь, запустите workflow
```

Порядок диагностики, если что-то не так:

| Симптом | Проверить |
|---|---|
| api не стартует, ошибка SSL к БД | `DATABASE_URL` — строка Neon целиком, с `sslmode`; TLS включается автоматически |
| CORS-ошибка в браузере | `CORS_ORIGINS` = точный origin Vercel (со схемой, без слэша) |
| Не логинится / «пропадает» сессия | `COOKIE_SAMESITE=none` **и** `COOKIE_SECURE=true`, оба на api |
| Live-логи не идут, обычные запросы ок | WS на тот же хост, что REST; проверьте `wss://` и `CORS_ORIGINS` |
| Запуски висят в `queued` | worker запущен и видит БД; scheduler — для cron-триггеров |

## Обновление секретов

`sync: false` Render подставляет **только при первичном создании** Blueprint.
Позже менять значения — вручную: Dashboard → сервис/группа → Environment.

## Стоимость

Минимум: Render free (api + 2 worker как free background workers — 2 из них
могут требовать платный минимальный план при нескольких worker'ах), Neon free,
Vercel free, UptimeRobot free. Детали планов — в консолях провайдеров.