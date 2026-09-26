from app.api.routes.auth import router as auth_router
from app.api.routes.executions import router as executions_router
from app.api.routes.hooks import router as hooks_router
from app.api.routes.invitations import router as invitations_router
from app.api.routes.node_types import router as node_types_router
from app.api.routes.schedules import router as schedules_router
from app.api.routes.workflows import router as workflows_router
from app.api.routes.workspaces import router as workspaces_router

__all__ = [
    "auth_router",
    "executions_router",
    "hooks_router",
    "invitations_router",
    "node_types_router",
    "schedules_router",
    "workflows_router",
    "workspaces_router",
]