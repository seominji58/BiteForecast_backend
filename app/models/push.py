"""푸시 알림 (2026-11-25).

- PushDevice: 폰마다 받은 FCM 토큰. 로그인한 사용자에 붙는다 (다른 계정으로 로그인하면 그 계정으로 옮긴다)
- PushPref: 알림 종류별 켜기·끄기 (줄이 없으면 전부 켜짐)
- PushLog: 같은 알림을 두 번 보내지 않게 (사용자·종류·키 하나당 한 번)
"""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime


class PushDevice(TimestampMixin, Base):
    __tablename__ = "push_device"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(512), unique=True)
    platform: Mapped[str] = mapped_column(String(10))  # android | ios
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PushPref(Base):
    __tablename__ = "push_pref"

    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    fav_good: Mapped[bool] = mapped_column(Boolean, default=True)  # 즐겨찾기 낚시터 내일 「좋음」
    trip_warning: Mapped[bool] = mapped_column(Boolean, default=True)  # 출조 날 특보
    weekly_best: Mapped[bool] = mapped_column(Boolean, default=True)  # 이번 주 가장 좋은 날


class PushLog(TimestampMixin, Base):
    __tablename__ = "push_log"
    __table_args__ = (UniqueConstraint("user_id", "kind", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    key: Mapped[str] = mapped_column(String(120))
