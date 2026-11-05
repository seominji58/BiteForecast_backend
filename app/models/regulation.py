from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, str_enum
from app.models.enums import RegulationStatus, ReportStatus, RestrictionType


class Restriction(Base):
    """장소별 규제정보 (FR-17~19). MVP 는 공식 고시 수동 조사 데이터"""

    __tablename__ = "restriction"

    restriction_id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"), index=True)
    restriction_type: Mapped[RestrictionType] = mapped_column(str_enum(RestrictionType))
    status: Mapped[RegulationStatus] = mapped_column(
        str_enum(RegulationStatus), default=RegulationStatus.UNVERIFIED
    )
    authority: Mapped[str | None] = mapped_column(String(100))
    legal_basis: Mapped[str | None] = mapped_column(String(200))
    notice_no: Mapped[str | None] = mapped_column(String(100))
    notice_url: Mapped[str | None] = mapped_column(String(500))
    geometry_source: Mapped[str | None] = mapped_column(String(200))
    geometry_accuracy: Mapped[str | None] = mapped_column(String(20))  # high / low / unknown
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    published_at: Mapped[date | None] = mapped_column(Date)
    verified_at: Mapped[date | None] = mapped_column(Date)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    update_state: Mapped[str | None] = mapped_column(String(20))  # ok / failed / revoked
    remarks: Mapped[str | None] = mapped_column(Text)


class RegulationReport(TimestampMixin, Base):
    """규제정보 오류 신고 (FR-21). 신고만으로 법적 상태는 바뀌지 않는다"""

    __tablename__ = "regulation_report"

    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[ReportStatus] = mapped_column(str_enum(ReportStatus), default=ReportStatus.PENDING)
