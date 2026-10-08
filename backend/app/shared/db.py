from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.shared.config import settings

# asyncpg не понимает эти query-параметры (sslmode - синтаксис libpq, а
# channel_binding ему вообще чужд) и падает с TypeError. Neon отдаёт строку
# именно с ними, поэтому вырезаем и переносим требование TLS в connect_args.
_UNSUPPORTED_QUERY = ("sslmode", "ssl", "channel_binding")


def normalize_database_url(raw: str) -> tuple[str, dict[str, Any]]:
    """URL драйвера -> (URL, connect_args) с корректным TLS для asyncpg.

    - приводит `postgresql://`/`postgres://` к `postgresql+asyncpg://` (у
      managed-провайдеров строка без драйвера);
    - вырезает libpq-параметры `sslmode`/`channel_binding`;
    - включает TLS, если он явно запрошен в URL (`sslmode`/`ssl`) либо задан
      `DB_SSL_REQUIRE`, либо хост - Neon (`*.neon.tech`).
    """
    url = make_url(raw)
    if url.drivername in ("postgresql", "postgres"):
        url = url.set(drivername="postgresql+asyncpg")

    ssl_requested = bool({"sslmode", "ssl"} & set(url.query))
    if url.query:
        url = url.set(
            query={k: v for k, v in url.query.items() if k not in _UNSUPPORTED_QUERY}
        )

    host = url.host or ""
    need_tls = ssl_requested or settings.db_ssl_require or host.endswith(".neon.tech")
    connect_args: dict[str, Any] = {"ssl": "require"} if need_tls else {}
    return url.render_as_string(hide_password=False), connect_args


_db_url, _connect_args = normalize_database_url(settings.database_url)
engine = create_async_engine(_db_url, connect_args=_connect_args)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
