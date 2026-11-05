from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    database_url: str = "sqlite:///./biteforecast.db"

    data_go_kr_api_key: str = ""
    kma_api_key: str = ""

    point_daily_cap: int = 0
    external_timeout_seconds: float = 5
    external_retries: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
