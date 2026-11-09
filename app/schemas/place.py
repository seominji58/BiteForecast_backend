from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.enums import PlaceType, StationRole
from app.schemas.common import ORMModel


class RegionOut(ORMModel):
    id: int
    name: str


class CoordOut(BaseModel):
    """좌표 품질 (가장 최근 검증 기록). 원본 좌표가 실제 낚시 지점인지 앱이 단정하지 않도록 함께 내려 준다"""

    grade: Literal["A", "B", "C", "D"]
    sub_grade: str | None
    location_type: str
    status: str
    # 대략 위치(대표 주소·반올림·공유 좌표) → 거리·위치를 「약」으로만 보여준다
    approx: bool
    # 화면에 그대로 쓰는 짧은 설명
    label: str
    checked_at: datetime


class PlaceOut(ORMModel):
    id: int
    region_id: int
    region_name: str
    name: str
    type: PlaceType
    lat: float | None
    lon: float | None
    address: str | None
    # 원본 좌표가 같은 시·군 낚시터들과 크게 어긋남 → 해황 자료를 연결하지 않는다 (DB 좌표는 그대로)
    location_suspect: bool = False
    # 좌표 검증 기록이 없으면 None (판단 안 됨)
    coord: CoordOut | None = None


class PlaceInfoOut(ORMModel):
    source: str
    address: str | None
    phone: str | None
    species: str | None
    fee: str | None
    facility: str | None
    manager: str | None
    data_date: str | None


class PlaceStationOut(ORMModel):
    role: StationRole
    station_id: int
    station_name: str
    provider: str
    distance_km: float | None  # None → 앱에서 "거리 확인 불가" 표시


class PlaceDetailOut(PlaceOut):
    info: PlaceInfoOut | None
    stations: list[PlaceStationOut]
