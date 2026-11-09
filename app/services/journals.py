"""낚시일지 생성/수정/삭제 (FR-08) + 사진·인증(재설계 v2 §9)

환경정보 연결(FR-10), 포인트·칭호 재계산(FR-11, 12)도 여기서 처리한다.
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AppUser, Journal, Place, Post, Species
from app.models.base import utcnow
from app.models.enums import PhotoPurpose
from app.schemas.journal import EnvSnapshotOut, JournalIn, JournalMutationOut, JournalOut, VerificationOut
from app.services import photos, trips, verification
from app.services.envlink import link_environment
from app.services.points import recompute_points
from app.services.titles import get_my_title

_ENV_FIELDS = ("place_id", "fished_at")
_FORM_ONLY = {"photo_ids", "request_verification"}


def _load_options():
    return (
        selectinload(Journal.place),
        selectinload(Journal.photos),
        selectinload(Journal.env_snapshots),
    )


def species_name(db: Session, code: str | None, etc: str | None) -> str | None:
    if code:
        sp = db.get(Species, code)
        return sp.name_ko if sp else code
    return etc


def to_out(db: Session, j: Journal) -> JournalOut:
    missing = verification.missing_conditions(j)
    shared = db.scalar(
        select(Post.id).where(Post.journal_id == j.id, Post.deleted_at.is_(None)).order_by(Post.id.desc())
    )
    return JournalOut(
        id=j.id,
        place_id=j.place_id,
        place_name=j.place.name,
        fished_at=j.fished_at,
        species_code=j.species_code,
        species_name=species_name(db, j.species_code, j.species_etc),
        species_etc=j.species_etc,
        count=j.count,
        max_length_cm=j.max_length_cm,
        bait=j.bait,
        rig=j.rig,
        memo=j.memo,
        photo_count=len(j.photos),
        photos=[photos.photo_out(p) for p in j.photos],
        verification=VerificationOut(
            status=j.verification_status,
            requested_at=j.verification_requested_at,
            reviewed_at=j.verification_reviewed_at,
            reject_reason=j.verification_reject_reason,
            points=verification.journal_points(db, j),
            can_request=not missing and j.verification_status in ("none", "rejected"),
            missing=missing,
        ),
        shared_post_id=shared,
        trip_stop_id=j.trip_stop_id,
        created_at=j.created_at,
        updated_at=j.updated_at,
        env_snapshots=[EnvSnapshotOut.model_validate(s) for s in j.env_snapshots],
    )


def list_journals(db: Session, user: AppUser) -> list[JournalOut]:
    rows = db.scalars(
        select(Journal)
        .where(Journal.user_id == user.id, Journal.deleted_at.is_(None))
        .order_by(Journal.fished_at.desc(), Journal.id.desc())
        .options(*_load_options())
    ).all()
    return [to_out(db, j) for j in rows]


def get_owned(db: Session, user: AppUser, journal_id: int) -> Journal:
    """다른 사용자의 일지는 존재 여부도 노출하지 않도록 404"""
    j = db.scalar(
        select(Journal)
        .where(Journal.id == journal_id, Journal.user_id == user.id, Journal.deleted_at.is_(None))
        .options(*_load_options())
    )
    if j is None:
        raise HTTPException(status_code=404, detail="일지를 찾을 수 없습니다")
    return j


def _validate_refs(db: Session, data: JournalIn) -> None:
    place = db.get(Place, data.place_id)
    if place is None or not place.is_active:
        raise HTTPException(status_code=400, detail="지원하지 않는 장소입니다")
    if data.species_code and db.get(Species, data.species_code) is None:
        raise HTTPException(status_code=400, detail="알 수 없는 어종 코드입니다")


def _finish(db: Session, user: AppUser, journal: Journal | None) -> JournalMutationOut:
    before = get_my_title(db, user)
    delta = recompute_points(db, user)
    after = get_my_title(db, user)
    db.commit()
    if journal is not None:
        db.expire(journal)
        journal = get_owned(db, user, journal.id)
    return JournalMutationOut(
        journal=to_out(db, journal) if journal is not None else None,
        point_delta=delta,
        total_points=after.total_points,
        title=after,
        title_changed=before.current.name != after.current.name,
    )


def _reload(db: Session, j: Journal) -> None:
    """사진 연결 후 관계(photos)를 다시 읽는다"""
    db.flush()
    db.refresh(j, attribute_names=["photos"])


def create_journal(db: Session, user: AppUser, data: JournalIn) -> JournalMutationOut:
    _validate_refs(db, data)
    if data.trip_stop_id is not None:
        trips.owned_stop_for_journal(db, user, data.trip_stop_id, data.place_id)
    j = Journal(user_id=user.id, **data.model_dump(exclude=_FORM_ONLY))
    db.add(j)
    db.flush()
    photos.attach(db, user, data.photo_ids or [], PhotoPurpose.JOURNAL, journal=j)
    _reload(db, j)
    link_environment(db, j)
    if data.request_verification:
        verification.request(j)
    return _finish(db, user, j)


def update_journal(db: Session, user: AppUser, journal_id: int, data: JournalIn) -> JournalMutationOut:
    j = get_owned(db, user, journal_id)
    _validate_refs(db, data)
    if data.trip_stop_id is not None and data.trip_stop_id != j.trip_stop_id:
        trips.owned_stop_for_journal(db, user, data.trip_stop_id, data.place_id)
    values = data.model_dump(exclude=_FORM_ONLY)
    if data.trip_stop_id is None:
        values.pop("trip_stop_id")  # 보내지 않으면 기존 연결 유지
    env_changed = any(getattr(j, f) != values[f] for f in _ENV_FIELDS)
    content_changed = any(getattr(j, f) != values[f] for f in verification.VERIFY_FIELDS)
    for k, v in values.items():
        setattr(j, k, v)
    photos_changed = photos.attach(db, user, data.photo_ids, PhotoPurpose.JOURNAL, journal=j)
    _reload(db, j)
    if env_changed:
        link_environment(db, j)
    verification.on_edit(j, content_changed or photos_changed)
    if data.request_verification:
        verification.request(j)
    return _finish(db, user, j)


def delete_journal(db: Session, user: AppUser, journal_id: int) -> JournalMutationOut:
    """소프트 삭제. 사진도 함께 삭제하고 포인트를 재계산(회수)한다"""
    j = get_owned(db, user, journal_id)
    j.deleted_at = utcnow()
    photos.delete_for(db, journal=j)
    db.flush()
    return _finish(db, user, None)


def request_verification(db: Session, user: AppUser, journal_id: int) -> JournalOut:
    j = get_owned(db, user, journal_id)
    verification.request(j)
    db.commit()
    return to_out(db, get_owned(db, user, journal_id))


def cancel_verification(db: Session, user: AppUser, journal_id: int) -> JournalOut:
    j = get_owned(db, user, journal_id)
    verification.cancel(j)
    db.commit()
    return to_out(db, get_owned(db, user, journal_id))
