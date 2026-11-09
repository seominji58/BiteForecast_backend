"""출조계획 입출력"""

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.place import PlaceOut
from app.schemas.summary import DataStatusOut, TideEventOut, ValueAt

# 설계안 §10 (사용자 승인 2026-11-09)
MAX_DAYS = 7
MAX_STOPS_PER_DAY = 5
MAX_AHEAD_DAYS = 365
MAX_PAST_DAYS = 30  # 막 다녀온 출조를 뒤늦게 적는 경우만 허용
MAX_CHECKLIST = 30
MAX_ACTIVE_PLANS = 50

Role = Literal["main", "alternative"]


def _blank(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


class TripStopIn(BaseModel):
    day: date
    place_id: int
    role: Role = "main"
    start_time: time | None = None
    end_time: time | None = None
    memo: str | None = Field(default=None, max_length=200)

    _b = field_validator("memo", mode="before")(classmethod(lambda cls, v: _blank(v)))


class TripStopPatch(BaseModel):
    """보낸 칸만 바꾼다"""

    day: date | None = None
    place_id: int | None = None
    role: Role | None = None
    start_time: time | None = None
    end_time: time | None = None
    memo: str | None = Field(default=None, max_length=200)
    sort_order: int | None = Field(default=None, ge=0, le=100)

    _b = field_validator("memo", mode="before")(classmethod(lambda cls, v: _blank(v)))


class ChecklistItemIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    checked: bool = False

    @field_validator("label", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class TripIn(BaseModel):
    """계획 만들기. title 을 비우면 「11/14 서산 출조」처럼 자동으로 붙인다"""

    title: str | None = Field(default=None, max_length=60)
    start_date: date
    end_date: date
    region: str | None = Field(default=None, max_length=20)
    species_code: str | None = Field(default=None, max_length=30)
    species_etc: str | None = Field(default=None, max_length=50)
    memo: str | None = Field(default=None, max_length=1000)
    stops: list[TripStopIn] = Field(default_factory=list, max_length=MAX_DAYS * MAX_STOPS_PER_DAY)
    # None 이면 기본 준비물로 채운다
    checklist: list[ChecklistItemIn] | None = Field(default=None, max_length=MAX_CHECKLIST)

    _b = field_validator("title", "region", "species_code", "species_etc", "memo", mode="before")(
        classmethod(lambda cls, v: _blank(v))
    )


class TripPatch(BaseModel):
    """보낸 칸만 바꾼다 (장소·준비물은 각자 API)"""

    title: str | None = Field(default=None, max_length=60)
    start_date: date | None = None
    end_date: date | None = None
    region: str | None = Field(default=None, max_length=20)
    species_code: str | None = Field(default=None, max_length=30)
    species_etc: str | None = Field(default=None, max_length=50)
    memo: str | None = Field(default=None, max_length=1000)

    _b = field_validator("title", "region", "species_code", "species_etc", "memo", mode="before")(
        classmethod(lambda cls, v: _blank(v))
    )


class TripStopOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    day: date
    place: PlaceOut
    role: Role
    sort_order: int
    start_time: time | None
    end_time: time | None
    memo: str | None
    # 이 장소에서 「기록 남기기」로 쓴 기록 ID
    journal_ids: list[int] = []


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    checked: bool


class TripOut(BaseModel):
    id: int
    title: str
    start_date: date
    end_date: date
    region: str | None
    species_code: str | None
    species_name: str | None
    species_etc: str | None
    memo: str | None
    stops: list[TripStopOut]
    checklist: list[ChecklistItemOut]
    created_at: datetime
    updated_at: datetime


class TripListItemOut(BaseModel):
    id: int
    title: str
    start_date: date
    end_date: date
    region: str | None
    stop_count: int
    checklist_done: int
    checklist_total: int
    journal_count: int
    # 첫 장소 (해황 요약은 outlook API 로)
    first_stop: TripStopOut | None


ForecastStatus = Literal["available", "pending", "past", "location_check"]


class StopOutlookOut(BaseModel):
    """장소 하나의 그날 해황 요약. 값을 만들지 않는다 — 없으면 null"""

    stop_id: int
    day: date
    place_id: int
    # available: 그날 예보 있음 · pending: 예보 발표 전 · past: 지난 날짜 · location_check: 좌표 확인 필요
    forecast_status: ForecastStatus
    wave_fc_max: ValueAt | None = None
    wind_fc_max: ValueAt | None = None
    # 특보는 「지금」 발효 상태. 오늘이 아닌 날짜면 warning_is_current=False → 앱은 「그날 특보 발표 전」
    warning_level: Literal["warning", "nearby", "preliminary", "none", "unknown"] | None = None
    warning_types: list[str] = []
    warning_is_current: bool = False
    tides: list[TideEventOut] = []


class TripOutlookOut(BaseModel):
    trip_id: int
    today: date
    # 받아 둔 기상청 예보가 하루 전체를 덮는 마지막 날짜 (KST)
    forecast_last_day: date | None
    stops: list[StopOutlookOut]
    data_status: DataStatusOut
