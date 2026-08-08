"""Application configuration.

All settings can be overridden via environment variables. Secrets (DB password,
app secret key) are resolved separately via app.core.secrets, never via plain
Settings fields, so they are never accidentally logged via a settings dump.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARDFORGE_", extra="ignore")

    app_name: str = "CardForge"
    environment: str = Field(default="production")  # production | development
    log_level: str = "INFO"

    # Auth model: single-user (no login, protected by network/reverse proxy only)
    # or multi-user (login + sessions). The data model always supports multiple
    # users; this toggle only controls whether the API enforces authentication.
    auth_mode: str = Field(default="single-user-no-login")  # single-user-no-login | multi-user

    # Postgres
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "cardforge"
    postgres_user: str = "cardforge"

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    # Data directories (bind-mounted from host, see docker-compose.yml)
    data_dir: str = "/data"
    scryfall_cache_dir: str = "/data/scryfall_cache"

    # Scryfall bulk import
    scryfall_user_agent: str = "CardForge/0.1 (+https://github.com/urza-lab/cardforge)"
    scryfall_bulk_auto_download: bool = True

    # Default languages supported by the UI (ISO 639-1)
    default_locale: str = "en"
    supported_locales: str = "en,de"

    def database_url(self, password: str) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache(maxsize=None)
def get_settings() -> Settings:
    return Settings()
