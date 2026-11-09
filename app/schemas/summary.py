from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ValueAt(BaseModel):
    v: float
    t: datetime


class IndexSummaryOut(BaseModel):
    """국립해양조사원 바다낚시지수 (현재 시간대) — 어종별 등급 중 가장 높은·낮은 등급. 앱 판정 아님"""

    period: str
    tide_phase: str | None
    best: str
    worst: str
    species_count: int
    station_km: float | None


class PlaceSummaryOut(BaseModel):
    """낚시터 1곳 요약. 실측(obs)과 예보(fc)는 다른 필드다 — 섞어 비교하지 않는다"""

    place_id: int
    warning_level: Literal["warning", "nearby", "preliminary", "none", "unknown"]
    warning_types: list[str]
    wave_obs: ValueAt | None  # 오늘 실측 최신
    wave_obs_km: float | None  # 실측 부이 거리
    wave_fc_max: ValueAt | None  # 남은 시간(오늘) 또는 그날 예보 최대
    wind_obs: ValueAt | None
    wind_fc_max: ValueAt | None
    temp_obs: ValueAt | None
    index: IndexSummaryOut | None


class DataStatusOut(BaseModel):
    """자료별 마지막 수집 시각과 오래됨 여부 (수집기가 멈췄을 때 최신처럼 보이지 않게)"""

    forecast_fetched_at: datetime | None  # 기상청 단기예보 (파고·풍속) 마지막 수집
    forecast_issued_at: datetime | None  # 받아 둔 예보 중 가장 최근 발표 시각 (오래됨 판단 기준)
    forecast_valid_until: datetime | None  # 받아 둔 예보가 다루는 마지막 시각 (이후 날짜는 예보 없음)
    warning_fetched_at: datetime | None  # 기상청 해상 특보
    buoy_fetched_at: datetime | None  # 해양관측부이 실측
    tide_fetched_at: datetime | None  # 조석 예보
    index_fetched_at: datetime | None  # 바다낚시지수
    # 예보 발표가 4시간 10분 넘게 없거나 특보 확인이 3시간 넘게 없으면 → 출조 탐색 판단에 쓰지 않는다
    stale: bool
    stale_reason: str | None
    stale_after_hours: int


class PlacesSummaryOut(BaseModel):
    date: str
    generated_at: datetime
    places: list[PlaceSummaryOut]
    disclaimer: str
    data_status: DataStatusOut
