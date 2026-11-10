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
# LOCATION_CHECK: 원본 좌표가 의심돼 자료를 연결하지 않음 / DIFFERENT_SEA: 가까운 조위관측소가 다른 바다를 봄
SeriesReason = Literal[
    "NO_STATION",
    "NO_DATA",
    "FUTURE_DATE",
    "NOT_CONNECTED",
    "TOO_FAR",
    "LOCATION_CHECK",
    "DIFFERENT_SEA",
    # 좌표 불일치 의심(추가 검증 필요) — 좌표 기준 자료는 판단 보류
    "LOCATION_REVIEW",
]


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

    metric: Literal[
        "tide_extreme", "tide_level", "wave_height", "wind_speed", "water_temp",
        "air_temp", "precipitation_probability", "sky_state", "precipitation_type",
    ]
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
    # 지수와 함께 발표된 환경 범위. 앱이 계산한 조건이나 실측값이 아니다.
    min_wave_m: float | None = None
    max_wave_m: float | None = None
    min_water_temp: float | None = None
    max_water_temp: float | None = None
    min_wind_ms: float | None = None
    max_wind_ms: float | None = None


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


class WarningMatchOut(BaseModel):
    type: str  # 예: 풍랑주의보 / 풍랑 예비특보
    areas: list[str]  # 이 장소의 바다에 해당하는 구역만
    when: str | None  # 예비특보의 예상 시각
    severe: bool  # 앞바다·도 단위 해상특보, 또는 선상 포인트의 먼바다 해상특보


class WarningOut(BaseModel):
    """기상청 해상 특보 (공식 발표). level=unknown 이면 「특보 없음」으로 표시하지 않는다"""

    level: Literal["warning", "nearby", "preliminary", "none", "unknown"]
    # active: 이 장소 해역에 특보 발효 / nearby: 인근 특보·예비특보
    # no_match: 다른 해역에만 특보 있음 / no_active_warnings: 발표된 해상 특보 없음
    # unknown_sea: 이 장소의 적용 해역을 모름 (특보 없음과 다름)
    # stale: 자료 만료 / collection_failed: 특보 API 수집 실패 / collector_failed: 수집기 주기 자체 실패
    # never_collected: 받은 적 없음 / location_check: 좌표 의심으로 연결 안 함
    status: Literal[
        "active", "nearby", "no_match", "no_active_warnings", "unknown_sea",
        "stale", "collection_failed", "collector_failed", "never_collected", "location_check",
    ] = "never_collected"
    # 자료 만료와 수집 실패는 동시에 성립할 수 있어 별도 문제 목록으로도 제공한다.
    issues: list[Literal["stale", "collection_failed", "collector_failed"]] = []
    reason: Literal["NO_DATA", "UNKNOWN_SEA", "LOCATION_CHECK", "LOCATION_REVIEW"] | None = None
    seas: list[str] = []  # 이 장소에 적용한 바다 (예: 서해중부)
    active: list[WarningMatchOut] = []
    preliminary: list[WarningMatchOut] = []
    issued_at: datetime | None = None
    fetched_at: datetime | None = None
    source: str = "기상청 기상특보"
    # 특보를 어떤 기준으로 연결했는지 — address: 등록 주소의 시·도·시군 → 특보 해역
    basis: Literal["address"] = "address"
    # 좌표 불일치 의심 곳: 주소 기준 특보의 한계 안내
    note: str | None = None
    # 참고용(실제 낚시 위치의 특보는 확인 안 됨). True 면 level 의 「none」을 「unknown」으로 바꿔 내려준다
    reference_only: bool = False
    # 참고용일 때 주소 기준으로 본 원래 단계 (예: none — 화면에서 「주소 기준으로는 특보 없음(참고)」)
    address_level: Literal["warning", "nearby", "preliminary", "none", "unknown"] | None = None


class PlaceCompareOut(BaseModel):
    place: PlaceOut
    region_name: str
    regulation: RegulationOut
    warning: WarningOut
    fishing_index: FishingIndexOut
    series: list[SeriesOut]


class CompareOut(BaseModel):
    date: date
    timezone: str = "Asia/Seoul"
    generated_at: datetime
    places: list[PlaceCompareOut]
    disclaimer: str


class PlaceConditionsOut(BaseModel):
    date: date
    timezone: str = "Asia/Seoul"
    generated_at: datetime
    place: PlaceCompareOut
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
