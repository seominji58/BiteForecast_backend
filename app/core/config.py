from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    # 기본은 로컬 SQLite. Supabase 등 PostgreSQL 은 postgresql://… 그대로 넣으면 psycopg 드라이버로 바꿔 쓴다
    database_url: str = "sqlite:///./biteforecast.db"

    @field_validator("database_url")
    @classmethod
    def _pg_driver(cls, v: str) -> str:
        for prefix in ("postgresql://", "postgres://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    data_go_kr_api_key: str = ""
    kma_api_key: str = ""
    # 경기데이터드림(openapi.gg.go.kr) 인증키 — 경기도 낚시어선업 현황 등. 서버에서만 사용
    gyeonggi_data_api_key: str = ""

    point_daily_cap: int = 0
    external_timeout_seconds: float = 10
    external_retries: int = 2
    # 공공데이터포털은 짧은 시간 연속 호출 시 429 를 반환하므로 호출 간 최소 간격을 둔다
    external_min_interval_seconds: float = 0.4

    # 비교 조회 가능 범위 (오늘 기준, KST). 수집 배치도 이 범위를 수집한다
    compare_days_back: int = 3
    compare_days_ahead: int = 7
    # 바다낚시지수 지점이 이보다 멀면 「가까운 지수 지점 없음」으로 표시
    fishing_index_max_km: float = 10

    # 커뮤니티: 신고 몇 회면 자동 숨김 / 좋아요 몇 개부터 인기글 표시
    community_hide_reports: int = 3
    community_popular_likes: int = 10

    # 사진: EXIF 제거·축소 후 이 폴더에 저장 (git 제외). 업로드 한도와 글·일지당 장수
    media_dir: str = "./media"
    photo_max_bytes: int = 10 * 1024 * 1024
    photo_max_side: int = 1600
    photo_max_per_item: int = 4
    # 업로드 후 일지·글에 연결되지 않은 사진은 이 시간이 지나면 정리 대상
    photo_orphan_hours: int = 24

    # 로그인: 구글 OAuth 클라이언트 ID (iOS·Android·Web, 쉼표로 구분). 비어 있으면 구글 로그인 비활성
    google_client_ids: str = ""
    # 로그인 유지 기간 (마지막 사용 후 이 기간이 지나면 다시 로그인)
    session_days: int = 60

    # 테스트 사용자(app_user.is_test)의 글·사진을 일반 화면에 보일지. 개발 중 기능 확인할 때만 true
    show_test_data: bool = False

    # 사진 인증 관리자 검토 (재설계 v2 §9). 비어 있으면 관리자 API·검토 화면을 막는다
    admin_token: str = ""
    # 촬영 시각(EXIF)과 출조 일시 차이가 이보다 크면 검토 화면에 「확인 필요」 표시 (자동 반려 아님)
    verification_time_gap_hours: int = 48


@lru_cache
def get_settings() -> Settings:
    return Settings()
