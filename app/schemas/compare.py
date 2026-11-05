from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.models.enums import DataKind, RegulationStatus, RestrictionType, TideExtremeType
from app.schemas.place import PlaceOut

SeriesStatus = Literal["ok", "unavailable"]

# unavailable 사유 (앱에서 문구로 변환)
#   NO_STATION     매핑된 관측소 없음
#   NO_DATA        관측소는 있으나 해당 날짜 자료 없음
#   FUTURE_DATE    미래 날짜에는 실측이 없음
#   NOT_CONNECTED  자료 출처가 아직 연결되지 않음 (예: 파고·풍속 예보)
#   TOO_FAR        가장 가까운 지점이 너무 멀어 표시하지 않음 (바다낚시지수)
SeriesReason = Literal["NO_STATION", "NO_DATA", "FUTURE_DATE", "NOT_CONNECTED", "TOO_FAR"]


class SourceOut(BaseModel):
    agency: str
    dataset: str
    station_code: str
    station_name: str
    distance_km: float | None  # None → 「거리 확인 불가」


class PointOut(BaseModel):
    t: datetime
    v: float | None  # None = 자료 없음 (0 과 구분, TC-02)


class ExtremeOut(BaseModel):
    t: datetime
    type: TideExtremeType
    v: float | None


class SeriesOut(BaseModel):
    """한 지표의 한 종류(예보/실측) 자료. 예보와 실측은 서로 다른 계열로 분리한다 (TC-03)"""

    metric: Literal["tide_extreme", "tide_level", "wave_height", "wind_speed", "water_temp"]
    unit: str
    kind: DataKind
    status: SeriesStatus
    reason: SeriesReason | None = None
    source: SourceOut | None = None
    issued_at: datetime | None = None  # 예보: 발표(조회) 시각 / 실측: 마지막 관측 시각
    fetched_at: datetime | None = None
    points: list[PointOut] | None = None
    extremes: list[ExtremeOut] | None = None


class RestrictionOut(BaseModel):
    restriction_type: RestrictionType
    status: RegulationStatus
    authority: str | None
    notice_no: str | None
    notice_url: str | None
    valid_from: date | None
    valid_to: date | None
    verified_at: date | None


class RegulationOut(BaseModel):
    """규제 상태 (FR-17~19). 자료가 없으면 UNVERIFIED — 「낚시 가능」으로 판정하지 않는다"""

    status: RegulationStatus
    stale: bool  # 마지막 확인이 오래됐거나 갱신 실패 → 「최신 여부 미확인」
    items: list[RestrictionOut]


class FishingSpeciesOut(BaseModel):
    species: str
    index: str | None  # 매우좋음/좋음/보통/나쁨/매우나쁨 (기관 발표값 그대로)


class FishingPeriodOut(BaseModel):
    period: str  # 오전 / 오후 / 일
    tide_phase: str | None
    items: list[FishingSpeciesOut]


class FishingIndexOut(BaseModel):
    """국립해양조사원 바다낚시지수. 앱이 판정한 값이 아니라 공식 발표 지수를 그대로 전달한다"""

    status: SeriesStatus
    reason: SeriesReason | None = None
    source: SourceOut | None = None
    fetched_at: datetime | None = None
    periods: list[FishingPeriodOut] | None = None


class PlaceCompareOut(BaseModel):
    place: PlaceOut
    region_name: str
    regulation: RegulationOut
    fishing_index: FishingIndexOut
    series: list[SeriesOut]


class CompareOut(BaseModel):
    date: date
    timezone: str = "Asia/Seoul"
    generated_at: datetime
    places: list[PlaceCompareOut]
    disclaimer: str


class DateRangeOut(BaseModel):
    today: date
    min: date
    max: date
    timezone: str = "Asia/Seoul"


class DataSourceOut(BaseModel):
    agency: str
    dataset: str
    kind: DataKind
    connected: bool
    note: str | None = None
