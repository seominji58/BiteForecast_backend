from app.models.enums import PlaceType, StationRole
from app.schemas.common import ORMModel


class RegionOut(ORMModel):
    id: int
    name: str


class PlaceOut(ORMModel):
    id: int
    region_id: int
    name: str
    type: PlaceType
    lat: float | None
    lon: float | None


class PlaceStationOut(ORMModel):
    role: StationRole
    station_id: int
    station_name: str
    provider: str
    distance_km: float | None  # None → 앱에서 "거리 확인 불가" 표시


class PlaceDetailOut(PlaceOut):
    stations: list[PlaceStationOut]
