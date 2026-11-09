from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, str_enum, utcnow
from app.models.enums import DataKind, Metric, VerificationStatus


class Journal(TimestampMixin, Base):
    """낚시일지 (FR-08). 삭제는 소프트 삭제"""

    __tablename__ = "journal"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"))
    fished_at: Mapped[datetime] = mapped_column(UTCDateTime())
    species_code: Mapped[str | None] = mapped_column(ForeignKey("species.code"))
    species_etc: Mapped[str | None] = mapped_column(String(50))
    count: Mapped[int | None] = mapped_column(Integer)
    max_length_cm: Mapped[float | None] = mapped_column(Float)
    bait: Mapped[str | None] = mapped_column(String(50))
    rig: Mapped[str | None] = mapped_column(String(50))
    memo: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # 출조계획의 장소에서 「기록 남기기」로 쓴 기록 (계획을 지우면 NULL)
    trip_stop_id: Mapped[int | None] = mapped_column(ForeignKey("trip_stop.id", ondelete="SET NULL"))

    # 사진 인증 (재설계 v2 §9). 포인트는 approved 일지에서만 계산된다
    verification_status: Mapped[VerificationStatus] = mapped_column(
        str_enum(VerificationStatus),
        default=VerificationStatus.NONE,
        server_default=VerificationStatus.NONE.value,
    )
    verification_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    verification_reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    verification_reject_reason: Mapped[str | None] = mapped_column(String(200))

    place: Mapped["Place"] = relationship()  # noqa: F821
    photos: Mapped[list["Photo"]] = relationship(  # noqa: F821
        primaryjoin="and_(Journal.id == foreign(Photo.journal_id), Photo.deleted_at.is_(None))",
        order_by="Photo.sort_order, Photo.id",
        viewonly=True,
    )
    env_snapshots: Mapped[list["JournalEnvSnapshot"]] = relationship(
        back_populates="journal", cascade="all, delete-orphan"
    )


class JournalEnvSnapshot(Base):
    """일지 ↔ 당시 인근 관측소 환경정보 (FR-10). 값이 없으면 value NULL 로 보관"""

    __tablename__ = "journal_env_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journal.id", ondelete="CASCADE"), index=True)
    metric: Mapped[Metric] = mapped_column(str_enum(Metric))
    kind: Mapped[DataKind | None] = mapped_column(str_enum(DataKind))  # None = 연결된 자료 없음
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10))
    value_time: Mapped[datetime | None] = mapped_column(UTCDateTime())
    station_id: Mapped[int | None] = mapped_column(ForeignKey("station.id"))
    distance_km: Mapped[float | None] = mapped_column(Float)
    source_agency: Mapped[str | None] = mapped_column(String(50))
    linked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    journal: Mapped[Journal] = relationship(back_populates="env_snapshots")
