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


class PlacesSummaryOut(BaseModel):
    date: str
    generated_at: datetime
    places: list[PlaceSummaryOut]
    disclaimer: str
