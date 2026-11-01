from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "URL Shortener"
    database_url: str = "sqlite:///./app.db"
    redis_url: str = ""  # empty -> in-memory cache fallback
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 60
    base_url: str = "http://localhost:8000"

    cache_ttl_seconds: int = 3600
    code_length: int = 7

    # Rate limits (requests per minute)
    create_limit_per_minute: int = 20
    login_limit_per_minute: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
