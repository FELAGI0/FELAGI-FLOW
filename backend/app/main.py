import contextlib
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI

from app.api.routes import (
    auth_router,
    executions_router,
    hooks_router,
    invitations_router,
    node_types_router,
    schedules_router,
    workflows_router,
    workspaces_router,
    ws_router,
)
from app.api.ws_manager import listen_manager
from app.shared.logging import setup_logging

setup_logging()

logger = structlog.get_logger()


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Поднимает LISTEN для live-логов на время жизни процесса API.

    БД может быть недоступна на старте (тесты на SQLite, ранний старт в
    compose) — тогда live-логи просто выключены, приложение не падает.
    """
    try:
        await listen_manager.start()
    except Exception as exc:
        logger.warning("ws.listen_unavailable", error=str(exc))
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            await listen_manager.stop()


app = FastAPI(title="Felagi Flow", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(invitations_router)
app.include_router(workspaces_router)
app.include_router(node_types_router)
app.include_router(workflows_router)
app.include_router(executions_router)
app.include_router(schedules_router)
# без префикса /api: путь /hooks/{token} — публичный приём вебхуков
app.include_router(hooks_router)
# без префикса /api: путь /ws/... проксируется Caddy как WebSocket
app.include_router(ws_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}