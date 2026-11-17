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


class MidSeaForecast(Base):
    """기상청 중기해상예보 (4~10일 뒤, 해역 단위 파고 범위·날씨). 2026-11-16 추가 (0007).
    낚시터 지점 예보가 아니라 넓은 해역 범위라서 화면에서는 「참고」로만 쓰고 조건 판정에는 쓰지 않는다"""

    __tablename__ = "mid_sea_forecast"
    __table_args__ = (UniqueConstraint("region", "tm_fc", "target_date", "period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    region: Mapped[str] = mapped_column(String(20), index=True)  # 서해중부 · 남해동부 · 제주도 …
    tm_fc: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)  # 발표 시각 (06시·18시 KST)
    target_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (KST)
    period: Mapped[str] = mapped_column(String(4))  # am · pm · day(8일 뒤부터는 하루 단위)
    wave_min: Mapped[float | None] = mapped_column(Float)
    wave_max: Mapped[float | None] = mapped_column(Float)
    weather: Mapped[str | None] = mapped_column(String(30))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())
