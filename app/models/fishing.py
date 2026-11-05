from datetime import date, datetime

from sqlalchemy import Date, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime


class FishingIndex(Base):
    """국립해양조사원 바다낚시지수 (공식 5단계 지수, 어종별).

    앱이 판정한 값이 아니라 기관 발표값을 그대로 저장·표시한다.
    period: 오전 / 오후 / 일 (가까운 날짜는 오전·오후, 이후는 하루 단위로 제공됨)
    """

    __tablename__ = "fishing_index"
    __table_args__ = (UniqueConstraint("station_id", "day", "period", "species"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("station.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    period: Mapped[str] = mapped_column(String(10))
    species: Mapped[str] = mapped_column(String(30))
    index: Mapped[str | None] = mapped_column(String(10))  # 매우좋음/좋음/보통/나쁨/매우나쁨
    tide_phase: Mapped[str | None] = mapped_column(String(20))  # 물때 (예: 소조기)
    min_wave_m: Mapped[float | None] = mapped_column(Float)
    max_wave_m: Mapped[float | None] = mapped_column(Float)
    min_water_temp: Mapped[float | None] = mapped_column(Float)
    max_water_temp: Mapped[float | None] = mapped_column(Float)
    min_wind_ms: Mapped[float | None] = mapped_column(Float)
    max_wind_ms: Mapped[float | None] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())
