"""장소별 규제정보 판정 (FR-17~20).

원칙
- 자료가 없으면 UNVERIFIED (「확인되지 않음」). 금지 자료가 없다는 이유로 OFFICIALLY_OPEN 을 주지 않는다
- 출조일이 유효기간에 포함되고 해제되지 않은 자료만 반영한다
- 위치 정확도가 낮은 자료는 자동 판정하지 않는다 (UNVERIFIED 유지)
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Restriction
from app.models.base import utcnow
from app.models.enums import RegulationStatus
from app.schemas.compare import RegulationOut, RestrictionOut

STALE_AFTER = timedelta(days=30)

# 여러 자료가 겹치면 더 강한 제한을 대표 상태로 쓴다
_PRIORITY = [
    RegulationStatus.PROHIBITED,
    RegulationStatus.CONDITIONAL,
    RegulationStatus.OFFICIALLY_OPEN,
]


def evaluate(db: Session, place_id: int, day: date) -> RegulationOut:
    rows = db.scalars(select(Restriction).where(Restriction.place_id == place_id)).all()
    active = [
        r
        for r in rows
        if (r.valid_from is None or r.valid_from <= day)
        and (r.valid_to is None or day <= r.valid_to)
        and r.update_state != "revoked"
        and r.geometry_accuracy != "low"
    ]

    status = RegulationStatus.UNVERIFIED
    for candidate in _PRIORITY:
        if any(r.status == candidate for r in active):
            status = candidate
            break

    now = utcnow()
    stale = any(
        r.update_state == "failed" or r.last_checked_at is None or now - r.last_checked_at > STALE_AFTER
        for r in active
    )
    return RegulationOut(
        status=status,
        stale=stale,
        items=[
            RestrictionOut(
                restriction_type=r.restriction_type,
                status=r.status,
                authority=r.authority,
                notice_no=r.notice_no,
                notice_url=r.notice_url,
                valid_from=r.valid_from,
                valid_to=r.valid_to,
                verified_at=r.verified_at,
            )
            for r in active
        ],
    )
