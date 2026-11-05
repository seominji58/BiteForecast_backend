from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, str_enum
from app.models.enums import PointReason


class PointLedger(TimestampMixin, Base):
    """포인트 원장 (append-only). 정정은 음수 행으로 기록 (FR-11, TC-05/06)

    ref_key: 중복 방지 키. 예) JOURNAL_CREATED → "journal:12", FIRST_PLACE → "place:3"
    """

    __tablename__ = "point_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    reason: Mapped[PointReason] = mapped_column(str_enum(PointReason))
    ref_key: Mapped[str] = mapped_column(String(64))
    delta: Mapped[int] = mapped_column(Integer)
    journal_id: Mapped[int | None] = mapped_column(ForeignKey("journal.id", ondelete="SET NULL"))


class Title(Base):
    """칭호 기준 테이블 (FR-12)"""

    __tablename__ = "title"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30))
    min_points: Mapped[int] = mapped_column(Integer, unique=True)
    sort_order: Mapped[int] = mapped_column(Integer)
