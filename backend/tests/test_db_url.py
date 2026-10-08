"""Нормализация DATABASE_URL для managed-Postgres (Neon) - app/shared/db.py.

Neon отдаёт строку вида postgresql://...?sslmode=require&channel_binding=require,
а asyncpg эти параметры не понимает (sslmode -> TypeError). Проверяем, что
normalize_database_url приводит URL к драйверу asyncpg, вырезает лишнее и
включает TLS там, где он нужен.
"""

import pytest

from app.shared import config
from app.shared.db import normalize_database_url


def test_neon_url_gets_driver_and_tls() -> None:
    url, connect_args = normalize_database_url(
        "postgresql://u:p@ep-cool-1.us-east-1.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )
    assert url.startswith("postgresql+asyncpg://")
    # libpq-параметры вырезаны
    assert "sslmode" not in url
    assert "channel_binding" not in url
    assert connect_args == {"ssl": "require"}


def test_neon_host_detected_without_sslmode() -> None:
    """TLS включается и без sslmode - по домену *.neon.tech."""
    url, connect_args = normalize_database_url("postgresql://u:p@ep-x.neon.tech/db")
    assert url.startswith("postgresql+asyncpg://")
    assert connect_args == {"ssl": "require"}


def test_local_url_untouched() -> None:
    """Локальный asyncpg-URL остаётся как есть, без TLS."""
    url, connect_args = normalize_database_url(
        "postgresql+asyncpg://felagi:change_me_in_prod@postgres:5432/felagi"
    )
    assert url == "postgresql+asyncpg://felagi:change_me_in_prod@postgres:5432/felagi"
    assert connect_args == {}


def test_sslmode_on_plain_host_requests_tls() -> None:
    """Не-Neon хост с sslmode=require тоже получает TLS."""
    url, connect_args = normalize_database_url(
        "postgresql://u:p@db.example.com:5432/d?sslmode=require"
    )
    assert url.startswith("postgresql+asyncpg://")
    assert "sslmode" not in url
    assert connect_args == {"ssl": "require"}


def test_db_ssl_require_flag_forces_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB_SSL_REQUIRE=true включает TLS независимо от хоста и URL."""
    monkeypatch.setattr(config.settings, "db_ssl_require", True)
    url, connect_args = normalize_database_url("postgresql://u:p@db.internal:5432/d")
    assert connect_args == {"ssl": "require"}
    assert url.startswith("postgresql+asyncpg://")