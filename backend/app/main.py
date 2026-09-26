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
)
from app.shared.logging import setup_logging

setup_logging()

app = FastAPI(title="Felagi Flow")
app.include_router(auth_router)
app.include_router(invitations_router)
app.include_router(workspaces_router)
app.include_router(node_types_router)
app.include_router(workflows_router)
app.include_router(executions_router)
app.include_router(schedules_router)
# без префикса /api: путь /hooks/{token} — публичный приём вебхуков
app.include_router(hooks_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}