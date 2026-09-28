# API

## OpenAPI

FastAPI генерирует документацию автоматически:

- **Swagger UI:** `http://localhost/docs`
- **ReDoc:** `http://localhost/redoc`
- **OpenAPI JSON:** `http://localhost/openapi.json`

Ниже — обзор основных эндпоинтов с примерами. Схемы ответов — источник истины,
дублировать их целиком смысла нет; примеры показывают форму запросов.

## Аутентификация

Схема — JWT: **access-токен** (короткий, в теле ответа) + **refresh-токен**
(долгий, в httpOnly-cookie). Access передаётся в заголовке
`Authorization: Bearer <token>`.

- Access живёт `ACCESS_TOKEN_EXPIRE_MINUTES` (по умолчанию 15 минут).
- Refresh — в cookie `refresh_token` (`HttpOnly`, `SameSite=Lax`), живёт
  `REFRESH_TOKEN_EXPIRE_DAYS` (30 дней). При `POST /api/auth/refresh` токен
  **ротируется**; используется только по cookie, из JS недоступен.
- При регистрации пользователю сразу создаётся workspace с ролью `owner`.

### POST /api/auth/register

```bash
curl -X POST http://localhost/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"me@example.com","password":"password123","name":"Me"}'
```

`201 Created`:

```json
{"access_token":"eyJhbGci..."}
```

Ошибки: `409` — email уже зарегистрирован; `422` — невалидные данные.

### POST /api/auth/login

```bash
curl -X POST http://localhost/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"me@example.com","password":"password123"}'
```

`200 OK` → `{"access_token":"..."}` (и cookie). `401` — неверные данные
(одинаковая ошибка для «нет пользователя» и «не тот пароль»).

### POST /api/auth/refresh

Только по cookie (теле нет). `200` → новый `access_token`, cookie ротируется.
`401` — cookie нет/истекла/неверного типа.

### POST /api/auth/logout

`204 No Content`, очищает refresh-cookie.

### GET /api/auth/me

```bash
curl http://localhost/api/auth/me -H "Authorization: Bearer $TOKEN"
```

`200` → `{"id": "...", "email": "...", "name": "...", "created_at": "..."}`.

## Workspaces

Bearer обязателен; доступ — по членству.

| Метод | Путь | Роль |
|---|---|---|
| GET | `/api/workspaces` | любая (свои workspace'ы) |
| GET | `/api/workspaces/{ws_id}` | member+ |
| PATCH | `/api/workspaces/{ws_id}` | owner/admin |
| DELETE | `/api/workspaces/{ws_id}` | owner |
| GET | `/api/workspaces/{ws_id}/members` | member+ |
| PATCH | `/api/workspaces/{ws_id}/members/{user_id}` | owner |
| DELETE | `/api/workspaces/{ws_id}/members/{user_id}` | owner/admin |

```bash
curl http://localhost/api/workspaces -H "Authorization: Bearer $TOKEN"
```

```json
[
  {
    "id": "…", "name": "Me's workspace", "slug": "me",
    "plan": "free", "current_user_role": "owner", "created_at": "…"
  }
]
```

`403` — нет членства; `404` — workspace не существует.

## Приглашения

| Метод | Путь | Роль |
|---|---|---|
| POST | `/api/workspaces/{ws_id}/invitations` | owner/admin |
| GET | `/api/workspaces/{ws_id}/invitations` | owner/admin |
| DELETE | `/api/workspaces/{ws_id}/invitations/{invitation_id}` | owner/admin |
| POST | `/api/invitations/{token}/accept` | по токену |

Ссылка-приглашение — `{FRONTEND_URL}/invite/{token}`, живёт
`INVITATION_EXPIRE_DAYS` (7 дней).

## Credentials

Секреты воркспейса (сейчас Telegram bot-токен), зашифрованные Fernet. Наружу
отдаются только метаданные — `payload`/`encrypted_payload` не возвращаются
никогда. Удаление — soft-delete (`deleted_at`).

| Метод | Путь | Роль |
|---|---|---|
| GET | `/api/workspaces/{ws_id}/credentials` | member+ |
| POST | `/api/workspaces/{ws_id}/credentials` | owner/admin |
| DELETE | `/api/workspaces/{ws_id}/credentials/{id}` | owner/admin |

```bash
curl -X POST http://localhost/api/workspaces/$WS_ID/credentials \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"service":"telegram","name":"My bot","payload":{"token":"123:ABC"}}'
```

`201 Created`:

```json
{"id":"…","service":"telegram","auth_type":"bot_token","name":"My bot","created_at":"…"}
```

Поле `payload` — свободный объект; для `service="telegram"` ожидается
`{"token": "<bot token>"}`. Секрет шифруется ключом `FERNET_KEY` и кладётся в
БД как `encrypted_payload` (bytea). `GET` возвращает `{"items": [...]}` без
секрета. `DELETE` (204) помечает credential удалённым: узлы, ссылающиеся на
него, при запуске получают ошибку шага «credential deleted».

## Node types

```bash
curl http://localhost/api/node-types -H "Authorization: Bearer $TOKEN"
```

Каталог типов узлов (метаданные + JSON-Schema параметров) — единый источник для
палитры редактора и валидации графа. Публичный, но требует авторизации.

## Workflows

| Метод | Путь | Роль |
|---|---|---|
| POST | `/api/workspaces/{ws_id}/workflows` | member+ |
| GET | `/api/workspaces/{ws_id}/workflows` | member+ |
| GET | `/api/workflows/{workflow_id}` | member+ |
| PATCH | `/api/workflows/{workflow_id}` | owner/admin |
| DELETE | `/api/workflows/{workflow_id}` | owner/admin |
| POST | `/api/workflows/{workflow_id}/versions` | member+ |
| GET | `/api/workflows/{workflow_id}/versions` | member+ |
| GET | `/api/workflows/{workflow_id}/versions/{version}` | member+ |
| POST | `/api/workflows/{workflow_id}/publish` | owner/admin |

Сохранение версии (черновика) и публикация валидируют граф; невалидный граф →
`422` с перечнем ошибок. Публикация синхронизирует расписания и вебхук-маршруты
из графа (см. `schedules`, `webhooks`) и переводит workflow в `active`.

### Запуск workflow

```bash
curl -X POST http://localhost/api/workflows/$WF_ID/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"payload":{"name":"Alice"}}'
```

`201 Created`:

```json
{
  "id": "…", "workflow_id": "…", "workflow_version_id": "…",
  "status": "queued", "trigger_type": "manual",
  "trigger_payload": {"name":"Alice"},
  "attempts": 0, "max_attempts": 3, "error": null,
  "created_at": "…", "started_at": null, "finished_at": null
}
```

`payload` доступен узлам как `{{ trigger.payload.* }}`. `409` — workflow не
опубликован. Требуется роль member+.

## Executions

### GET /api/executions/{execution_id}

Детали запуска со всеми шагами (шаги отсортированы по `sequence`):

```bash
curl http://localhost/api/executions/$EXEC_ID -H "Authorization: Bearer $TOKEN"
```

```json
{
  "id": "…", "status": "succeeded", "attempts": 1, "max_attempts": 3,
  "created_at": "…", "started_at": "…", "finished_at": "…",
  "steps": [
    {
      "id": "…", "node_id": "d", "node_type": "debug", "attempt": 1,
      "status": "succeeded", "input": {"message": "hi"},
      "output": {"level": "info"}, "error": null, "warnings": [],
      "duration_ms": 1
    }
  ]
}
```

`404` — запуск не найден; `403` — нет членства в workspace его workflow.

### GET /api/workspaces/{ws_id}/executions

Список с фильтрами и keyset-пагинацией.

Query-параметры:
- `workflow_id` (uuid, опц.) — фильтр по workflow;
- `status` — `queued`|`running`|`succeeded`|`failed`|`dead`|`canceled`;
- `limit` — 1..100 (по умолчанию 20);
- `cursor` — непрозрачный курсор из `next_cursor` предыдущей страницы.

```bash
curl "http://localhost/api/workspaces/$WS_ID/executions?status=failed&limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{"items": [ /* ExecutionResponse[] */ ], "next_cursor": "MTIzf…" }
```

`next_cursor = null` — страниц больше нет. `400` — невалидный курсор.

### POST /api/executions/{execution_id}/cancel

Отмена — best-effort: ставит флаг, runner проверяет его между узлами.

```bash
curl -X POST http://localhost/api/executions/$EXEC_ID/cancel \
  -H "Authorization: Bearer $TOKEN"
```

`200` → обновлённый execution со `status="canceled"`. `409` — нельзя отменить
запуск в терминальном статусе.

## WebSocket: live-логи

```
ws://localhost/ws/executions/{execution_id}?token=<access_token>
```

Токен — **в query-параметре**, потому что браузерный WebSocket не умеет
кастомные заголовки. Сервер отвечает прикладными кодами закрытия:

| Код | Значение |
|---|---|
| 4401 | невалидный/просроченный токен |
| 4404 | запуск не найден или нет доступа |
| 4429 | превышен лимит соединений пользователя (`WS_MAX_CONNECTIONS_PER_USER`) |
| 1000 | нормальное завершение (после `finished`) |

Сообщения (JSON):

```jsonc
// при подключении: состояние + все шаги
{"type": "snapshot", "execution": { /* … */ }, "steps": [ /* … */ ]}

// новые шаги (дедуплицировать по id)
{"type": "steps", "steps": [ /* … */ ]}

// терминальный статус; после этого сервер закрывает соединение (1000)
{"type": "finished", "status": "succeeded", "error": null}

// keep-alive (клиент может игнорировать)
{"type": "ping"}
```

Пример на клиенте — `frontend/src/api/ws.ts` (`connectExecutionLogs`) и хук
`useExecutionLogs`. Снапшот снимается на подключении, поэтому после `finished`
актуальные метаданные (`attempts`, `started_at`, `finished_at`) дочитываются
через `GET /api/executions/{id}`.

## Публичные вебхуки

```
/hooks/{token}
```

Уникальный маршрут без `/api`-префикса: принимает `GET` или `POST` (набор
методов задаётся узлом `trigger_webhook` и проверяется при публикации). Не
требует JWT — доступ по секретному токену.

**POST:**

```bash
curl -X POST http://localhost/hooks/$TOKEN \
  -H "Content-Type: application/json" \
  -d '{"hello":"world"}'
```

`202 Accepted`:

```json
{"execution_id": "…"}
```

**GET** — если узел разрешает `GET`. Иначе `405` с заголовком
`Allow: POST`. Тело запроса (JSON или текст), заголовки и query-параметры
попадают в `trigger_payload` и доступны узлам как `{{ trigger.payload.* }}`.

Ошибки: `404` — токен неизвестен; `404` — workflow маршрута не найден;
`409` — workflow не опубликован (нет активной версии).

## Cron-расписания

### GET /api/workspaces/{ws_id}/schedules

Список расписаний workspace (роль member+).

```json
[
  {
    "id": "…", "workflow_id": "…", "spec": "0 9 * * *",
    "next_run_at": "…", "last_run_at": "…", "enabled": true
  }
]
```

Расписания не редактируются напрямую — они синхронизируются из графа при
публикации workflow. Управление — через узел `trigger_cron` в редакторе.

## Health

```
GET /healthz   # без авторизации
```

```json
{"status": "ok"}
```

Используется healthcheck'ами compose и CI-смоуком.