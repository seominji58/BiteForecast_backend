from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime


class AppUser(TimestampMixin, Base):
    """MVP: 로그인 없이 기기 UUID 로 식별 (명세 D-2)"""

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Favorite(TimestampMixin, Base):
    __tablename__ = "favorite"

    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"), primary_key=True)
