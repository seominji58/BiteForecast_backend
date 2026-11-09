from app.models.enums import PlaceType, StationRole
from app.schemas.common import ORMModel


class RegionOut(ORMModel):
    id: int
    name: str


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
