"""LISTEN/NOTIFY-менеджер для live-логов (этап 5.B).

Один выделенный asyncpg-коннект на процесс API: LISTEN занимает соединение
целиком, поэтому SQLAlchemy-pool здесь не подходит. Получив NOTIFY, менеджер
кладёт payload в очереди активных WS-соединений ЭТОГО процесса (fan-out).
При нескольких репликах API каждая держит свой LISTEN и получает уведомление
сама — рассылает только в свои соединения (DESIGN.md §3).
"""

import asyncio
import uuid

import asyncpg
import structlog

from app.engine.notify import CHANNEL
from app.shared.config import settings

logger = structlog.get_logger()


def _asyncpg_dsn() -> str:
    """SQLAlchemy-URL (postgresql+asyncpg://…) → DSN, понятный asyncpg."""
    return settings.database_url.replace("+asyncpg", "")


class ListenManager:
    """Держит LISTEN и раздаёт уведомления подписчикам процесса."""

    def __init__(self) -> None:
        self._connection: asyncpg.Connection | None = None
        self._subscribers: dict[str, set[asyncio.Queue[str]]] = {}
        # счётчик открытых WS-соединений на пользователя (лимит из настроек)
        self._per_user: dict[str, int] = {}

    @property
    def started(self) -> bool:
        return self._connection is not None

    async def start(self) -> None:
        if self._connection is not None:
            return
        # регистрацию соединений начинаем с чистого листа: старт приложения —
        # единственная точка, где состояние заведомо пусто (важно и для тестов,
        # где менеджер — модульный синглтон)
        self._per_user.clear()
        self._connection = await asyncpg.connect(_asyncpg_dsn())
        await self._connection.add_listener(CHANNEL, self._on_notify)
        logger.info("ws.listen_started", channel=CHANNEL)

    async def stop(self) -> None:
        if self._connection is None:
            return
        await self._connection.remove_listener(CHANNEL, self._on_notify)
        await self._connection.close()
        self._connection = None
        self._subscribers.clear()
        self._per_user.clear()
        logger.info("ws.listen_stopped")

    def _on_notify(
        self, _connection: object, _pid: int, _channel: str, payload: str
    ) -> None:
        for queue in list(self._subscribers.get(payload, ())):
            queue.put_nowait(payload)

    def subscribe(self, execution_id: uuid.UUID) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers.setdefault(str(execution_id), set()).add(queue)
        return queue

    def unsubscribe(self, execution_id: uuid.UUID, queue: asyncio.Queue[str]) -> None:
        subscribers = self._subscribers.get(str(execution_id))
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(str(execution_id), None)

    def register_connection(self, user_id: uuid.UUID) -> bool:
        """True, если лимит одновременных соединений на пользователя не исчерпан."""
        key = str(user_id)
        if self._per_user.get(key, 0) >= settings.ws_max_connections_per_user:
            return False
        self._per_user[key] = self._per_user.get(key, 0) + 1
        return True

    def release_connection(self, user_id: uuid.UUID) -> None:
        key = str(user_id)
        remaining = self._per_user.get(key, 0) - 1
        if remaining > 0:
            self._per_user[key] = remaining
        else:
            self._per_user.pop(key, None)


listen_manager = ListenManager()