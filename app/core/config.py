from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    database_url: str = "sqlite:///./biteforecast.db"

    data_go_kr_api_key: str = ""
    kma_api_key: str = ""

    point_daily_cap: int = 0
    external_timeout_seconds: float = 10
    external_retries: int = 2
    # 공공데이터포털은 짧은 시간 연속 호출 시 429 를 반환하므로 호출 간 최소 간격을 둔다
    external_min_interval_seconds: float = 0.4

    # 비교 조회 가능 범위 (오늘 기준, KST). 수집 배치도 이 범위를 수집한다
    compare_days_back: int = 3
    compare_days_ahead: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
