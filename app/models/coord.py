"""낚시터 좌표 검증 기록 (docs/03_데이터/2026-11-09_좌표품질_검증보고서.md §6·§12).

- 원본 좌표(place.lat/lon)는 바꾸지 않는다. 이 테이블은 「검증 기록」만 쌓는다
- 이력 보존: 기록을 고치거나 지우지 않고 새 기록을 추가한다. 장소의 현재 상태 = 가장 최근 기록
- batch: 한 번에 등록한 묶음 이름 (되돌릴 때 이 단위로 지운다)
"""

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, utcnow

# A 실제 낚시 위치 검증 · B 대표 위치 확인 · C 미확인·정밀도 부족 · D 좌표 오류 의심
GRADES = ("A", "B", "C", "D")
# C1 정밀 좌표·의미 미확인 · C2 정밀도 부족(대략·공유 좌표)
SUB_GRADES = ("C1", "C2")
# 좌표가 무엇의 위치인지 (근거가 없으면 unknown)
LOCATION_TYPES = (
    "fishing_spot",  # 실제 낚시 위치
    "harbor",  # 승선장·출발 항구
    "business_address",  # 사업장·어촌계 대표 주소
    "approx_area",  # 대략적인 지역 좌표
    "agency_point",  # 기관 지정 대표 지점
    "unverifiable",  # 위치 확인 불가 (오류 의심)
    "unknown",  # 근거 없음
)
# 검증 상태
STATUSES = ("unverified", "needs_review", "verified")
# 확인 출처
METHODS = ("audit", "juso", "vworld", "agency", "manual")


class PlaceCoordCheck(Base):
    __tablename__ = "place_coord_check"
    __table_args__ = (Index("ix_coord_check_place_time", "place_id", "checked_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"))
    grade: Mapped[str] = mapped_column(String(1))
    sub_grade: Mapped[str | None] = mapped_column(String(4))
    location_type: Mapped[str] = mapped_column(String(20), default="unknown")
    status: Mapped[str] = mapped_column(String(16), default="unverified")
    method: Mapped[str] = mapped_column(String(10))
    # 근거 자료 (보고서 경로·URL·문의 회신 번호 등)
    source_ref: Mapped[str | None] = mapped_column(String(300))
    # 판단 근거 (사람이 읽는 설명)
    evidence: Mapped[str] = mapped_column(Text)
    # 보정 후보 (저장이 허용된 출처만 — 예: 사람 확인·행안부 주소 좌표. VWorld 결과는 저장하지 않는다)
    candidate_lat: Mapped[float | None] = mapped_column(Float)
    candidate_lon: Mapped[float | None] = mapped_column(Float)
    candidate_note: Mapped[str | None] = mapped_column(String(300))
    batch: Mapped[str] = mapped_column(String(40), index=True)
    checked_by: Mapped[str | None] = mapped_column(String(60))
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
