"""Публикация уведомлений о ходе выполнения (этап 5.B, live-логи).

Канал один на всех: payload — только execution_id. Уведомление не несёт сами
данные (лимит NOTIFY 8 КБ), клиент дочитывает шаги из БД; источник истины —
всегда БД, NOTIFY fire-and-forget (DESIGN.md §3).
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CHANNEL = "exec_log"


async def notify_exec_log(session: AsyncSession, execution_id: uuid.UUID) -> None:
    """Публикует pg_notify в ТЕКУЩЕЙ транзакции.

    Postgres доставляет NOTIFY только при COMMIT — вызывающий обязан
    закоммитить, иначе уведомление не уйдёт. Канал и payload передаются
    bind-параметрами (не склейкой в SQL).

    На не-postgres диалектах (SQLite в тестах без TEST_DATABASE_URL) pg_notify
    отсутствует — молча пропускаем: live-логи есть только на реальной БД.
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": CHANNEL, "payload": str(execution_id)},
    )