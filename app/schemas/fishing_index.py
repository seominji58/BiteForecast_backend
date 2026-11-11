"""어종별 공식 바다낚시지수 (국립해양조사원 발표값 그대로). 앱이 판정한 값이 아니다"""

from datetime import date, datetime

from pydantic import BaseModel


class IndexSpeciesOut(BaseModel):
    species: str  # 지수의 어종 이름 그대로 (「-」는 「어종 공통」)
    grades: dict[str, str]  # 시간대(오전·오후·일) → 등급. 발표된 시간대만


class IndexPlaceLinkOut(BaseModel):
    place_id: int
    distance_km: float | None
    # True: 공식 지수 지점 자체로 등록된 낚시터 / False: 지점 근처 일반 낚시터(참고)
    official: bool


class IndexPointOut(BaseModel):
    station_id: int
    station_name: str
    tide_phase: dict[str, str | None]  # 시간대 → 물때 (발표값)
    species: list[IndexSpeciesOut]
    places: list[IndexPlaceLinkOut]


class FishingIndexDayOut(BaseModel):
    date: date
    periods: list[str]  # 그날 발표된 시간대 (예: 오전·오후 또는 일)
    fetched_at: datetime | None
    max_km: float  # 일반 낚시터를 지점과 연결하는 최대 거리
    points: list[IndexPointOut]
    disclaimer: str
