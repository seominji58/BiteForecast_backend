from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, str_enum, utcnow
from app.models.enums import DataKind, Metric


class Journal(TimestampMixin, Base):
    """낚시일지 (FR-08). 삭제는 소프트 삭제"""

    __tablename__ = "journal"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"))
    fished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    species_code: Mapped[str | None] = mapped_column(ForeignKey("species.code"))
    species_etc: Mapped[str | None] = mapped_column(String(50))
    count: Mapped[int | None] = mapped_column(Integer)
    max_length_cm: Mapped[float | None] = mapped_column(Float)
    bait: Mapped[str | None] = mapped_column(String(50))
    rig: Mapped[str | None] = mapped_column(String(50))
    memo: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    photos: Mapped[list["JournalPhoto"]] = relationship(back_populates="journal")
    env_snapshots: Mapped[list["JournalEnvSnapshot"]] = relationship(back_populates="journal")


class JournalPhoto(TimestampMixin, Base):
    """사진 (FR-09). EXIF 제거 후 저장, 기본 비공개"""

    __tablename__ = "journal_photo"

    id: Mapped[int] = mapped_column(primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journal.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(255))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    journal: Mapped[Journal] = relationship(back_populates="photos")


class JournalEnvSnapshot(Base):
    """일지 ↔ 당시 인근 관측소 환경정보 (FR-10). 값이 없으면 value NULL 로 보관"""

    __tablename__ = "journal_env_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journal.id", ondelete="CASCADE"), index=True)
    metric: Mapped[Metric] = mapped_column(str_enum(Metric))
    kind: Mapped[DataKind] = mapped_column(str_enum(DataKind))
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10))
    value_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    station_id: Mapped[int | None] = mapped_column(ForeignKey("station.id"))
    distance_km: Mapped[float | None] = mapped_column(Float)
    source_agency: Mapped[str | None] = mapped_column(String(50))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    journal: Mapped[Journal] = relationship(back_populates="env_snapshots")
