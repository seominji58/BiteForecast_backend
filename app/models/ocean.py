from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, str_enum
from app.models.enums import DataKind, Metric, TideExtremeType


class TideForecast(Base):
    """시간별 예측 조위 (FR-03). value NULL = 자료 없음 (0 과 구분)"""

    __tablename__ = "tide_forecast"
    __table_args__ = (UniqueConstraint("station_id", "t", "issued_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("station.id"), index=True)
    t: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    level_cm: Mapped[float | None] = mapped_column(Float)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime())
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())


class TideExtreme(Base):
    """만조/간조 (FR-03)"""

    __tablename__ = "tide_extreme"
    __table_args__ = (UniqueConstraint("station_id", "t", "issued_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("station.id"), index=True)
    t: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    type: Mapped[TideExtremeType] = mapped_column(str_enum(TideExtremeType))
    level_cm: Mapped[float | None] = mapped_column(Float)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime())
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())


class OceanReading(Base):
    """파고·풍속·수온 등. 예보/실측은 kind 로 분리 저장하고 응답에서도 섞지 않는다 (TC-03)"""

    __tablename__ = "ocean_reading"
    __table_args__ = (UniqueConstraint("station_id", "metric", "kind", "t", "issued_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("station.id"), index=True)
    metric: Mapped[Metric] = mapped_column(str_enum(Metric))
    kind: Mapped[DataKind] = mapped_column(str_enum(DataKind))
    t: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10))
    quality_flag: Mapped[int | None] = mapped_column(Integer)
    # 실측은 issued_at 이 없으므로 t 와 같은 값을 넣어 UNIQUE 제약을 유지한다
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime())
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())
