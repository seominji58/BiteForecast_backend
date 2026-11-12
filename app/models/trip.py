"""출조계획 (설계안 docs/05_UX/2026-11-09_출조계획_설계안.md).

계획은 로그인한 본인만 본다. 해황 값은 저장하지 않고 볼 때마다 최신 예보로 계산한다.
"""

from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, utcnow


class TripPlan(TimestampMixin, Base):
    __tablename__ = "trip_plan"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(60))
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date)
    region: Mapped[str | None] = mapped_column(String(20))
    species_code: Mapped[str | None] = mapped_column(ForeignKey("species.code"))
    species_etc: Mapped[str | None] = mapped_column(String(50))
    memo: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    stops: Mapped[list["TripStop"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="TripStop.day, TripStop.sort_order, TripStop.id",
    )
    checklist: Mapped[list["TripChecklistItem"]] = relationship(
        cascade="all, delete-orphan", order_by="TripChecklistItem.sort_order, TripChecklistItem.id"
    )


class TripStop(Base):
    """계획의 날짜별 장소. role: main(주 장소) · alternative(예비)"""

    __tablename__ = "trip_stop"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("trip_plan.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date)
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"))
    role: Mapped[str] = mapped_column(String(12), default="main")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    memo: Mapped[str | None] = mapped_column(String(200))

    plan: Mapped[TripPlan] = relationship(back_populates="stops")
    place: Mapped["Place"] = relationship()  # noqa: F821


class TripChecklistItem(Base):
    __tablename__ = "trip_checklist_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("trip_plan.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(40))
    checked: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # 함께 가는 출조: 공용 준비물 담당자 (만든 사람 또는 참여자). 없으면 담당 미정
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))


class TripMember(TimestampMixin, Base):
    """함께 가는 사람 (만든 사람은 trip_plan.user_id — 이 표에는 참여자만)"""

    __tablename__ = "trip_member"
    __table_args__ = (UniqueConstraint("plan_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("trip_plan.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    # joined 참여 · maybe 미정 · declined 불참
    status: Mapped[str] = mapped_column(String(12), default="joined")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class TripInvite(TimestampMixin, Base):
    """초대 코드 (만든 사람이 만들고 끌 수 있음, 만료 시각 있음)"""

    __tablename__ = "trip_invite"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("trip_plan.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
