"""낚시일지 생성/수정/삭제 (FR-08) + 환경정보 연결(FR-10) + 포인트·칭호 재계산(FR-11, 12)"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AppUser, Journal, Place, Species
from app.models.base import utcnow
from app.schemas.journal import EnvSnapshotOut, JournalIn, JournalMutationOut, JournalOut
from app.services.envlink import link_environment
from app.services.points import recompute_points
from app.services.titles import get_my_title

_ENV_FIELDS = ("place_id", "fished_at")


def _load_options():
    return (
        selectinload(Journal.place),
        selectinload(Journal.photos),
        selectinload(Journal.env_snapshots),
    )


def to_out(db: Session, j: Journal) -> JournalOut:
    species_name = None
    if j.species_code:
        sp = db.get(Species, j.species_code)
        species_name = sp.name_ko if sp else j.species_code
    elif j.species_etc:
        species_name = j.species_etc

    return JournalOut(
        id=j.id,
        place_id=j.place_id,
        place_name=j.place.name,
        fished_at=j.fished_at,
        species_code=j.species_code,
        species_name=species_name,
        species_etc=j.species_etc,
        count=j.count,
        max_length_cm=j.max_length_cm,
        bait=j.bait,
        rig=j.rig,
        memo=j.memo,
        photo_count=sum(1 for p in j.photos if p.deleted_at is None),
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
        db.refresh(journal)
    return JournalMutationOut(
        journal=to_out(db, journal) if journal is not None else None,
        point_delta=delta,
        total_points=after.total_points,
        title=after,
        title_changed=before.current.name != after.current.name,
    )


def create_journal(db: Session, user: AppUser, data: JournalIn) -> JournalMutationOut:
    _validate_refs(db, data)
    j = Journal(user_id=user.id, **data.model_dump())
    db.add(j)
    db.flush()
    link_environment(db, j)
    return _finish(db, user, j)


def update_journal(db: Session, user: AppUser, journal_id: int, data: JournalIn) -> JournalMutationOut:
    j = get_owned(db, user, journal_id)
    _validate_refs(db, data)
    values = data.model_dump()
    env_changed = any(getattr(j, f) != values[f] for f in _ENV_FIELDS)
    for k, v in values.items():
        setattr(j, k, v)
    if env_changed:
        link_environment(db, j)
    return _finish(db, user, j)


def delete_journal(db: Session, user: AppUser, journal_id: int) -> JournalMutationOut:
    """소프트 삭제. 사진도 함께 삭제 처리하고 포인트를 재계산(회수)한다"""
    j = get_owned(db, user, journal_id)
    now = utcnow()
    j.deleted_at = now
    for p in j.photos:
        if p.deleted_at is None:
            p.deleted_at = now
    db.flush()
    return _finish(db, user, None)
