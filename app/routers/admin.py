"""관리자 사진 인증 검토 (재설계 v2 §9). X-Admin-Token 헤더(ADMIN_TOKEN)로 보호한다.

최소 기능: 대기 목록 → 사진·기록·사전 검사 참고 정보 → 승인 / 반려(사유)
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import AdminOnly, DbSession
from app.models import AppUser, Journal
from app.models.enums import VerificationStatus
from app.schemas.photo import PhotoOut
from app.services import photos, verification
from app.services.community import nicknames
from app.services.journals import species_name
from app.services.points import recompute_points

router = APIRouter(prefix="/admin", tags=["admin"])


class PrecheckOut(BaseModel):
    photo_id: int
    taken_at: datetime | None
    time_note: str
    time_flag: bool
    duplicate_journal_ids: list[int]
    duplicate_other_user: bool


class ReviewItem(BaseModel):
    journal_id: int
    author: str
    place_name: str
    fished_at: datetime
    species_name: str | None
    count: int | None
    max_length_cm: float | None
    memo: str | None
    status: VerificationStatus
    requested_at: datetime | None
    reviewed_at: datetime | None
    reject_reason: str | None
    photos: list[PhotoOut]
    precheck: list[PrecheckOut]


class RejectIn(BaseModel):
    reason: str = Field(min_length=2, max_length=200)

    @field_validator("reason", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


def _item(db, j: Journal) -> ReviewItem:
    return ReviewItem(
        journal_id=j.id,
        author=nicknames(db, {j.user_id})[j.user_id],
        place_name=j.place.name,
        fished_at=j.fished_at,
        species_name=species_name(db, j.species_code, j.species_etc),
        count=j.count,
        max_length_cm=j.max_length_cm,
        memo=j.memo,
        status=j.verification_status,
        requested_at=j.verification_requested_at,
        reviewed_at=j.verification_reviewed_at,
        reject_reason=j.verification_reject_reason,
        photos=[photos.photo_out(p) for p in j.photos],
        precheck=[PrecheckOut(**c) for c in verification.precheck(db, j)],
    )


def _get(db, journal_id: int) -> Journal:
    j = db.scalar(
        select(Journal)
        .where(Journal.id == journal_id, Journal.deleted_at.is_(None))
        .options(selectinload(Journal.place), selectinload(Journal.photos))
    )
    if j is None:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다")
    return j


@router.get("/verifications", response_model=list[ReviewItem], dependencies=[AdminOnly])
def list_verifications(
    db: DbSession, status: Literal["pending", "approved", "rejected"] = "pending", limit: int = 50
):
    rows = db.scalars(
        select(Journal)
        .where(Journal.deleted_at.is_(None), Journal.verification_status == status)
        .order_by(Journal.verification_requested_at.asc() if status == "pending" else Journal.id.desc())
        .limit(min(max(limit, 1), 200))
        .options(selectinload(Journal.place), selectinload(Journal.photos))
    ).all()
    return [_item(db, j) for j in rows]


@router.post("/verifications/{journal_id}/approve", response_model=ReviewItem, dependencies=[AdminOnly])
def approve(journal_id: int, db: DbSession):
    """승인 → 작성자 포인트 재계산. 이미 승인된 기록을 다시 승인해도 포인트는 한 번만 반영된다"""
    j = _get(db, journal_id)
    verification.approve(j)
    recompute_points(db, db.get(AppUser, j.user_id))
    db.commit()
    return _item(db, _get(db, journal_id))


@router.post("/verifications/{journal_id}/reject", response_model=ReviewItem, dependencies=[AdminOnly])
def reject(journal_id: int, data: RejectIn, db: DbSession):
    """반려(사유 필수) → 승인됐던 기록이면 포인트 회수"""
    j = _get(db, journal_id)
    verification.reject(j, data.reason)
    recompute_points(db, db.get(AppUser, j.user_id))
    db.commit()
    return _item(db, _get(db, journal_id))


_PAGE = Path(__file__).resolve().parent.parent / "static" / "admin.html"


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def admin_page():
    """검토 화면 (토큰은 화면에서 입력, 브라우저 세션에만 보관)"""
    return HTMLResponse(_PAGE.read_text(encoding="utf-8"))
