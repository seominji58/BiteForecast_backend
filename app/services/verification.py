"""낚시일지 사진 인증 (재설계 v2 §9).

상태: none(개인 기록) → pending(검토 대기) → approved(인증 완료) / rejected(반려, 사유)
- 신청 조건: 사진 1장 이상 + 어종(목록 또는 직접 입력). 장소·일시는 일지 필수값
- 포인트는 approved 일지에서만 계산 (services/points.py). 승인을 여러 번 해도 같은 일지는 한 번만 반영
- 인증과 관련된 내용(장소·일시·어종·마릿수·길이·사진)을 고치면 다시 검토 대기로 돌아간다
- 사전 검사(같은 사진 재사용, 촬영 시각 차이)는 관리자 참고 정보일 뿐, 자동 반려하지 않는다
"""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AppUser, Journal, Photo, PointLedger
from app.models.base import utcnow
from app.models.enums import VerificationStatus as VS

# 인증 판단에 영향을 주는 일지 필드
VERIFY_FIELDS = ("place_id", "fished_at", "species_code", "species_etc", "count", "max_length_cm")


def missing_conditions(j: Journal) -> list[str]:
    missing = []
    if not j.photos:
        missing.append("사진 1장 이상")
    if not (j.species_code or j.species_etc):
        missing.append("어종")
    return missing


def journal_points(db: Session, j: Journal) -> int:
    return int(
        db.scalar(select(func.coalesce(func.sum(PointLedger.delta), 0)).where(PointLedger.journal_id == j.id))
        or 0
    )


def request(j: Journal) -> None:
    """검토 신청 (none·rejected → pending). 이미 대기·완료면 그대로"""
    if j.verification_status in (VS.PENDING, VS.APPROVED):
        return
    missing = missing_conditions(j)
    if missing:
        raise HTTPException(
            status_code=400, detail=f"인증 신청에 필요한 항목이 없습니다: {', '.join(missing)}"
        )
    j.verification_status = VS.PENDING
    j.verification_requested_at = utcnow()
    j.verification_reviewed_at = None
    j.verification_reject_reason = None


def cancel(j: Journal) -> None:
    if j.verification_status != VS.PENDING:
        raise HTTPException(status_code=400, detail="검토 대기 중인 기록만 신청을 취소할 수 있습니다")
    j.verification_status = VS.NONE
    j.verification_requested_at = None


def on_edit(j: Journal, content_changed: bool) -> None:
    """일지를 고친 뒤 호출. 인증 관련 내용이 바뀌면 다시 검토 대기로 (승인됐던 포인트는 재계산에서 회수)"""
    if not content_changed or j.verification_status not in (VS.PENDING, VS.APPROVED):
        return
    if missing_conditions(j):
        # 사진을 모두 빼는 등 조건이 깨지면 신청 자체를 내린다
        j.verification_status = VS.NONE
        j.verification_requested_at = None
    else:
        j.verification_status = VS.PENDING
        j.verification_requested_at = utcnow()
    j.verification_reviewed_at = None


# --- 관리자 ---


def approve(j: Journal) -> bool:
    """승인. 이미 승인된 기록이면 아무것도 바꾸지 않는다 (중복 지급 없음). 반환: 상태가 바뀌었는지"""
    if j.verification_status == VS.APPROVED:
        return False
    if j.verification_status != VS.PENDING:
        raise HTTPException(status_code=409, detail="검토 대기 중인 기록만 승인할 수 있습니다")
    j.verification_status = VS.APPROVED
    j.verification_reviewed_at = utcnow()
    j.verification_reject_reason = None
    return True


def reject(j: Journal, reason: str) -> None:
    if j.verification_status not in (VS.PENDING, VS.APPROVED):
        raise HTTPException(status_code=409, detail="검토 대기 중이거나 승인된 기록만 반려할 수 있습니다")
    j.verification_status = VS.REJECTED
    j.verification_reviewed_at = utcnow()
    j.verification_reject_reason = reason


def precheck(db: Session, j: Journal) -> list[dict]:
    """사진별 참고 정보: 촬영 시각 차이, 다른 기록에서 쓰인 같은 사진 여부"""
    gap_limit = timedelta(hours=get_settings().verification_time_gap_hours)
    out = []
    for p in j.photos:
        if p.taken_at is None:
            time_note, time_flag = "촬영 시각 확인 불가 (EXIF 없음)", False
        else:
            gap = abs(p.taken_at - j.fished_at)
            hours = round(gap.total_seconds() / 3600, 1)
            src = "사진 정보" if p.taken_at_source == "exif" else "기기 제공"
            time_flag = gap > gap_limit
            time_note = f"촬영 시각({src})과 출조 일시 차이 {hours}시간"
        dup_rows = db.execute(
            select(Photo.journal_id, Journal.user_id)
            .join(Journal, Journal.id == Photo.journal_id)
            .where(
                Photo.sha256 == p.sha256,
                Photo.id != p.id,
                Photo.deleted_at.is_(None),
                Photo.journal_id.is_not(None),
                Photo.journal_id != j.id,
                Journal.deleted_at.is_(None),
            )
        ).all()
        out.append(
            {
                "photo_id": p.id,
                "taken_at": p.taken_at,
                "time_note": time_note,
                "time_flag": time_flag,
                "duplicate_journal_ids": sorted({r[0] for r in dup_rows}),
                "duplicate_other_user": any(r[1] != j.user_id for r in dup_rows),
            }
        )
    return out


def pending_count(db: Session, user: AppUser) -> int:
    return int(
        db.scalar(
            select(func.count()).where(
                Journal.user_id == user.id,
                Journal.deleted_at.is_(None),
                Journal.verification_status == VS.PENDING,
            )
        )
        or 0
    )
