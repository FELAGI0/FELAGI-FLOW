import json

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://felagi:felagi@localhost:5432/felagi"
    fernet_key: str = ""
    # JSON-массив строк, см. DESIGN.md §1 «Модели Anthropic»
    llm_models: str = "[]"
    log_level: str = "INFO"

    # без дефолта — приложение не стартует, пока секрет не задан
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    # secure=True только за TLS; в локальной разработке — False
    cookie_secure: bool = False

    # база для ссылок-приглашений: {frontend_url}/invite/{token}
    frontend_url: str = "http://localhost"
    invitation_expire_days: int = 7

    # ключ Anthropic для LLM-узла (этап 6 заменит его на credentials воркспейса)
    anthropic_api_key: str = ""

    # live-логи execution (этап 5.B): период ping, чтобы прокси не рвал idle-WS,
    # и лимит одновременных WS-соединений на одного пользователя
    ws_heartbeat_seconds: int = 30
    ws_max_connections_per_user: int = 5

    @property
    def llm_models_list(self) -> list[str]:
        models: list[str] = json.loads(self.llm_models)
        return models


settings = Settings()
