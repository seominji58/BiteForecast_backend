"""전국 낚시 탐험 도장 (2026-11-26). 장소 목록은 seeds/challenge_spots.json, 이 표는 방문 기록만.
좌표는 저장하지 않는다 — 장소·시각·거리 구간(100/300m)만"""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime


class ChallengeVisit(Base):
    __tablename__ = "challenge_visit"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"), index=True)
    season: Mapped[int] = mapped_column(Integer, default=1)
    visited_at: Mapped[datetime] = mapped_column(UTCDateTime())
    within_m: Mapped[int] = mapped_column(Integer)  # 100 또는 300 (정확한 거리는 저장 안 함)
