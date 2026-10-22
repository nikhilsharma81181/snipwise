from typing import Literal

from pydantic import PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "production"] = "production"

    database_url: PostgresDsn
    redis_url: RedisDsn
    frontend_origin: str = "http://localhost:3000"
    free_minutes_per_month: int = 60
    ai_rate_limit_per_minute: int = 20
    daily_token_cap: int = 200_000


settings = Settings()  # pyright: ignore[reportCallIssue]
