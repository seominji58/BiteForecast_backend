"""내 낚시 기록 요약·저장 직후 성취 (서비스 개선 설계 R1). 집계만 하고 저장하지 않는다."""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import KST
from app.models import AppUser, Journal
from app.models.enums import VerificationStatus
from app.schemas.records import MilestoneOut, RecordSummaryOut, SpeciesRecordOut
from app.services.journals import species_name
from app.services.points import species_key


def _caught(j: Journal) -> bool:
    """어종이 있고 「못 잡음」(마릿수 0)이 아닌 기록"""
    return species_key(j) is not None and j.count != 0


def _my_journals(db: Session, user: AppUser) -> list[Journal]:
    return list(
        db.scalars(
            select(Journal)
            .where(Journal.user_id == user.id, Journal.deleted_at.is_(None))
            .order_by(Journal.fished_at, Journal.id)
        )
    )


def summary(db: Session, user: AppUser) -> RecordSummaryOut:
    rows = _my_journals(db, user)
    days: dict = defaultdict(list)
    for j in rows:
        days[j.fished_at.astimezone(KST).date()].append(j)
    groups: dict[str, list[Journal]] = defaultdict(list)
    for j in rows:
        if _caught(j):
            groups[species_key(j)].append(j)

    species = []
    for key, js in groups.items():
        first = js[0]  # 출조 일시순
        with_len = [j for j in js if j.max_length_cm]
        best = max(with_len, key=lambda j: (j.max_length_cm, -j.fished_at.timestamp())) if with_len else None
        species.append(
            SpeciesRecordOut(
                key=key,
                species_code=first.species_code,
                species_name=species_name(db, first.species_code, first.species_etc) or "어종",
                first_at=first.fished_at,
                first_journal_id=first.id,
                journal_count=len(js),
                catch_count=sum(j.count or 0 for j in js),
                best_length_cm=best.max_length_cm if best else None,
                best_journal_id=best.id if best else None,
                best_at=best.fished_at if best else None,
                best_verified=bool(best and best.verification_status == VerificationStatus.APPROVED),
            )
        )
    species.sort(key=lambda s: s.first_at)
    return RecordSummaryOut(
        journal_count=len(rows),
        trip_days=len(days),
        skunk_days=sum(1 for js in days.values() if all(j.count == 0 for j in js)),
        first_trip=min(days) if days else None,
        last_trip=max(days) if days else None,
        species=species,
    )


def milestone(db: Session, user: AppUser, j: Journal) -> MilestoneOut | None:
    """방금 저장한 기록이 이 어종의 첫 기록이거나 최대어를 넘었는지 (내 다른 기록과 비교)"""
    if not _caught(j):
        return None
    key = species_key(j)
    others = [x for x in _my_journals(db, user) if x.id != j.id and _caught(x) and species_key(x) == key]
    name = species_name(db, j.species_code, j.species_etc) or "어종"
    if not others:
        return MilestoneOut(
            kind="first_catch", species_name=name, length_cm=j.max_length_cm, previous_cm=None
        )
    prev = max((x.max_length_cm for x in others if x.max_length_cm), default=None)
    if j.max_length_cm and prev and j.max_length_cm > prev:
        return MilestoneOut(
            kind="personal_best", species_name=name, length_cm=j.max_length_cm, previous_cm=prev
        )
    return None
