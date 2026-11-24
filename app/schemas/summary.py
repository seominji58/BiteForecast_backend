from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ValueAt(BaseModel):
    v: float
    t: datetime


class TideEventOut(BaseModel):
    type: Literal["high", "low"]
    t: datetime
    v: float | None
    station_name: str
    station_km: float | None


class IndexSummaryOut(BaseModel):
    """국립해양조사원 바다낚시지수 (현재 시간대) — 어종별 등급 중 가장 높은·낮은 등급. 앱 판정 아님"""

    period: str
    tide_phase: str | None
    best: str
    worst: str
    species_count: int
    station_km: float | None


class TempNormalOut(BaseModel):
    """근처 관측소의 예년 같은 달 평균 수온 (국립수산과학원). 실측과 비교하는 참고값"""

    v: float
    station: str
    km: float
    period: str  # 예: 2019~2025
    source: str


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
    # 가장 센 바람 시각의 풍향 (16방위, 바람이 불어오는 쪽. 예: 북서). 기상청 단기예보 VEC
    wind_dir_fc: str | None = None
    temp_obs: ValueAt | None
    # 근처 관측소 예년 같은 달 평균 수온 (실측과 비교해 「평년보다 +1.8°C」, 2026-11-24)
    temp_normal: TempNormalOut | None = None
    air_temp_fc_min: ValueAt | None = None
    air_temp_fc_max: ValueAt | None = None
    pop_fc_max: ValueAt | None = None
    precipitation_types: list[int] = []
    index: IndexSummaryOut | None
    # 원본 좌표 의심 → 자료 연결 안 함 (출조 후보·지도에서 제외)
    location_suspect: bool = False
    # 바다 권역 (특보 해역 기준): 서해 · 남해 · 동해 · 제주. 알 수 없으면 None
    sea_group: Literal["서해", "남해", "동해", "제주"] | None = None
    # 다음(오늘) 또는 그날 첫 만조·간조 — 같은 바다 조위관측소 예보일 때만
    next_tide: TideEventOut | None = None
    # 그날 만조·간조 전부 (같은 바다 조위관측소 예보일 때만). 전체 요약 응답에서는 빼서 보낸다
    tides: list[TideEventOut] = Field(default_factory=list, exclude=True)
    # 기상청 중기해상예보 (4~10일 뒤, 해역 단위 파고 범위). 단기예보가 없는 날의 참고 — 조건 판정에 쓰지 않는다
    mid_sea: "MidSeaOut | None" = None
    # 물때(몇 물): 음력 날짜로 정한다 (서해 7물때식, 남해·동해·제주 8물때식). 바다를 모르면 None
    mulddae: str | None = None
    mulddae_style: Literal["7물때식", "8물때식"] | None = None
    # 음력 날짜 출처: 「한국천문연구원」(음양력 정보) 또는 「계산」(합삭 계산식)
    lunar_source: str | None = None
    # 일출·일몰 (KST HH:MM, 낚시터 좌표 기준)
    sunrise: str | None = None
    sunset: str | None = None
    # 일출·일몰 출처: 「한국천문연구원」(출몰시각 정보) 또는 「계산」(NOAA 계산식)
    sun_source: str | None = None
    # 출입통제구역·연안사고 위험구역 짧은 안내 (해양경찰청 2023 공간정보와 좌표 대조). 금지 판정이 아니다
    zone_notes: list[str] = []


class MidSeaPeriodOut(BaseModel):
    period: Literal["am", "pm", "day"]
    wave_min: float | None
    wave_max: float | None
    weather: str | None


class MidSeaOut(BaseModel):
    region: str  # 예: 서해중부 (기상청 중기해상 구역)
    wave_min: float | None  # 그날 오전·오후 중 최저
    wave_max: float | None  # 그날 오전·오후 중 최고
    periods: list[MidSeaPeriodOut]
    issued_at: datetime


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


PlaceSummaryOut.model_rebuild()
