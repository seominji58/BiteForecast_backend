from sqlalchemy import Boolean, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, str_enum
from app.models.enums import PlaceType, StationKind, StationRole


class Region(Base):
    """지원 해역 (MVP 2~3곳)"""

    __tablename__ = "region"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    places: Mapped[list["Place"]] = relationship(back_populates="region")


class Place(Base):
    """낚시 장소 (사전 구축 시드 데이터)"""

    __tablename__ = "place"

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("region.id"))
    name: Mapped[str] = mapped_column(String(100), index=True)
    type: Mapped[PlaceType] = mapped_column(str_enum(PlaceType), default=PlaceType.OTHER)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    region: Mapped[Region] = relationship(back_populates="places")
    stations: Mapped[list["PlaceStation"]] = relationship(back_populates="place")
    info: Mapped["PlaceInfo | None"] = relationship(back_populates="place", uselist=False)

    @property
    def region_name(self) -> str:
        return self.region.name

    @property
    def address(self) -> str | None:
        return self.info.address if self.info else None


class Station(Base):
    """관측소/예보 지점"""

    __tablename__ = "station"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))  # 예: KHOA, KMA
    external_id: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[StationKind] = mapped_column(str_enum(StationKind))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)


class PlaceStation(Base):
    """장소 ↔ 기준 관측소 매핑. 거리는 매핑 시 Haversine 으로 계산해 저장 (FR-07)"""

    __tablename__ = "place_station"

    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"), primary_key=True)
    role: Mapped[StationRole] = mapped_column(str_enum(StationRole), primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("station.id"))
    distance_km: Mapped[float | None] = mapped_column(Float)  # None = 거리 확인 불가

    place: Mapped[Place] = relationship(back_populates="stations")
    station: Mapped[Station] = relationship()


class PlaceInfo(Base):
    """장소 부가정보 (출처별로 있는 항목만)"""

    __tablename__ = "place_info"

    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    species: Mapped[str | None] = mapped_column(String(200))
    fee: Mapped[str | None] = mapped_column(String(300))
    facility: Mapped[str | None] = mapped_column(String(100))
    manager: Mapped[str | None] = mapped_column(String(100))
    data_date: Mapped[str | None] = mapped_column(String(20))

    place: Mapped[Place] = relationship(back_populates="info")


class Species(Base):
    __tablename__ = "species"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    name_ko: Mapped[str] = mapped_column(String(50))
