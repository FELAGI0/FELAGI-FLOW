import json

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://felagi:felagi@localhost:5432/felagi"
    fernet_key: str = ""
    # JSON-массив строк, см. DESIGN.md §1 «Модели Anthropic»
    llm_models: str = "[]"
    log_level: str = "INFO"

    @property
    def llm_models_list(self) -> list[str]:
        models: list[str] = json.loads(self.llm_models)
        return models


settings = Settings()
