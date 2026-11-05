"""활동 포인트 (FR-11) — 원장 재계산(derive) 방식.

**인증 완료(approved) 일지만** 포인트 대상이다 (재설계 v2 §9).
사진을 올리거나 일지를 저장하는 것만으로는 지급하지 않는다.

일지·인증 상태가 바뀔 때마다 사용자의 인증 완료 일지 전체로 "있어야 할 포인트 이벤트"를 다시 계산하고,
현재 원장 잔액과의 차이만 append-only 행으로 기록한다.

- 같은 일지를 여러 번 승인·재저장해도 차이가 0 이므로 중복 지급되지 않는다 (키 = 사유 + 일지 ID, TC-05)
- 인증이 반려·취소되거나 일지가 삭제되면 없어진 이벤트는 음수 행으로 회수된다 (TC-06)
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AppUser, Journal, PointLedger
from app.models.enums import PointReason, VerificationStatus

# 「사진 첨부 +5」(PHOTO_ATTACHED)는 폐지 — 사진은 인증 조건이므로 중복.
# 과거 원장 행의 이름 표시용으로 enum 만 남긴다
POINTS: dict[PointReason, int] = {
    PointReason.JOURNAL_CREATED: 10,
    PointReason.DETAIL_FILLED: 5,
    PointReason.FIRST_PLACE: 15,
    PointReason.PERSONAL_BEST: 20,
}

EventKey = tuple[PointReason, str]  # (사유, 중복 방지 키)


@dataclass(frozen=True)
class ExpectedEvent:
    delta: int
    journal_id: int


def species_key(j: Journal) -> str | None:
    """최대어 비교 단위. 직접 입력 어종은 공백·대소문자를 무시하고 같은 어종으로 본다"""
    if j.species_code:
        return f"code:{j.species_code}"
    if j.species_etc:
        return "etc:" + "".join(j.species_etc.split()).lower()
    return None


def expected_events(journals: list[Journal]) -> dict[EventKey, ExpectedEvent]:
    """인증 완료 일지 목록(출조 일시순)으로 있어야 할 이벤트를 계산한다"""
    events: dict[EventKey, ExpectedEvent] = {}
    seen_places: set[int] = set()
    best_by_species: dict[str, float] = {}

    for j in sorted(journals, key=lambda x: (x.fished_at, x.id)):
        ref = f"journal:{j.id}"
        events[(PointReason.JOURNAL_CREATED, ref)] = ExpectedEvent(POINTS[PointReason.JOURNAL_CREATED], j.id)

        sp = species_key(j)
        if sp and j.max_length_cm:
            events[(PointReason.DETAIL_FILLED, ref)] = ExpectedEvent(POINTS[PointReason.DETAIL_FILLED], j.id)

        # 장소별 가장 이른 인증 일지 1건에 귀속. 그 일지가 빠지면 다음 인증 일지로 넘어간다
        if j.place_id not in seen_places:
            seen_places.add(j.place_id)
            events[(PointReason.FIRST_PLACE, f"place:{j.place_id}")] = ExpectedEvent(
                POINTS[PointReason.FIRST_PLACE], j.id
            )

        # 인증 일지끼리, 같은 어종의 직전 최대 길이를 "초과"할 때만. 어종의 첫 기록은 갱신이 아니다 (명세 D-9)
        if sp and j.max_length_cm:
            prev = best_by_species.get(sp)
            if prev is not None and j.max_length_cm > prev:
                events[(PointReason.PERSONAL_BEST, ref)] = ExpectedEvent(
                    POINTS[PointReason.PERSONAL_BEST], j.id
                )
            if prev is None or j.max_length_cm > prev:
                best_by_species[sp] = j.max_length_cm

    return events


def recompute_points(db: Session, user: AppUser) -> int:
    """원장을 기대 상태에 맞춘다. 반환값 = 이번에 추가된 증감 합계 (flush 만 하고 commit 은 호출자가 한다)"""
    db.flush()  # 세션이 autoflush=False 라서, 방금 바꾼 인증 상태·삭제를 조회에 반영
    approved = list(
        db.scalars(
            select(Journal).where(
                Journal.user_id == user.id,
                Journal.deleted_at.is_(None),
                Journal.verification_status == VerificationStatus.APPROVED,
            )
        ).all()
    )
    expected = expected_events(approved)

    current: dict[EventKey, int] = defaultdict(int)
    for reason, ref_key, total in db.execute(
        select(PointLedger.reason, PointLedger.ref_key, func.sum(PointLedger.delta))
        .where(PointLedger.user_id == user.id)
        .group_by(PointLedger.reason, PointLedger.ref_key)
    ).all():
        current[(reason, ref_key)] = total

    applied = 0
    for key in sorted(set(expected) | set(current), key=lambda k: (k[0].value, k[1])):
        exp = expected.get(key)
        diff = (exp.delta if exp else 0) - current.get(key, 0)
        if diff == 0:
            continue
        reason, ref_key = key
        journal_id = exp.journal_id if exp else _journal_id_from_ref(ref_key)
        db.add(
            PointLedger(user_id=user.id, reason=reason, ref_key=ref_key, delta=diff, journal_id=journal_id)
        )
        applied += diff

    db.flush()
    return applied


def _journal_id_from_ref(ref_key: str) -> int | None:
    kind, _, value = ref_key.partition(":")
    return int(value) if kind == "journal" and value.isdigit() else None
