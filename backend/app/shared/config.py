import json
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://felagi:felagi@localhost:5432/felagi"
    # требовать TLS к Postgres независимо от хоста; managed-Postgres (Neon)
    # определяется ещё и по домену - см. app/shared/db.py
    db_ssl_require: bool = False
    fernet_key: str = ""
    # метка ключа Fernet, которым зашифрованы credentials (ПРАВКА 12).
    # Сейчас всегда одно значение; поле заложено под будущую ротацию ключей.
    fernet_key_id: str = "default"
    # JSON-массив разрешённых моделей LLM-узла; пусто = любые
    llm_models: str = "[]"
    log_level: str = "INFO"

    # без дефолта - приложение не стартует, пока секрет не задан
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    # secure=True только за TLS; в локальной разработке - False
    cookie_secure: bool = False
    # SameSite refresh-cookie: "lax" - когда фронт и api на одном сайте (Caddy
    # локально), "none" - когда они на разных доменах (Vercel -> Render), иначе
    # браузер не отправит cookie в cross-site запросе. "none" требует Secure.
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # JSON-массив origin'ов фронтенда для CORS; пусто = cross-origin запрещён
    # (локально фронт и api отдаёт один Caddy, CORS не нужен)
    cors_origins: str = "[]"

    # база для ссылок-приглашений: {frontend_url}/invite/{token}
    frontend_url: str = "http://localhost"
    invitation_expire_days: int = 7

    # ключ и адрес OpenAI-совместимого API для LLM-узла
    # (этап 6 заменит это на credentials воркспейса)
    llm_base_url: str = "http://185.221.214.224:4100/v1"
    llm_api_key: str = ""

    # live-логи execution (этап 5.B): период ping, чтобы прокси не рвал idle-WS,
    # и лимит одновременных WS-соединений на одного пользователя
    ws_heartbeat_seconds: int = 30
    ws_max_connections_per_user: int = 5

    # как часто воркер возвращает в очередь запуски умерших воркеров
    # (см. app/worker/__main__.py, maybe_reclaim)
    reclaim_interval_seconds: int = 30

    @property
    def llm_models_list(self) -> list[str]:
        models: list[str] = json.loads(self.llm_models)
        return models

    @property
    def cors_origins_list(self) -> list[str]:
        origins: list[str] = json.loads(self.cors_origins)
        return origins


settings = Settings()
