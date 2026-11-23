"""활동 포인트 (FR-11) — 원장 재계산(derive) 방식.

2026-11-23 바뀜: 사진 인증(관리자 승인) 없이 **활동만으로** 쌓인다 (카페 등급처럼).
- 낚시 기록: 기록 +10, 어종·크기까지 +5, 처음 간 낚시터 +15, 같은 어종 최대어 갱신 +20
- 커뮤니티: 글 +5 (하루 3개까지), 댓글 +1 (하루 10개까지) — 도배로 등급을 올리지 못하게

활동이 바뀔 때마다 「있어야 할 포인트 이벤트」를 다시 계산하고 원장 잔액과의 차이만 append-only 로 기록한다.
- 같은 기록을 여러 번 저장해도 차이가 0 이라 중복 지급 없음 (키 = 사유 + 대상 ID)
- 기록·글·댓글을 지우면 없어진 이벤트는 음수 행으로 회수된다
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AppUser, Comment, Journal, PointLedger, Post
from app.models.enums import PointReason

# 「사진 첨부 +5」(PHOTO_ATTACHED)는 폐지 — 사진은 인증 조건이므로 중복.
# 과거 원장 행의 이름 표시용으로 enum 만 남긴다
POINTS: dict[PointReason, int] = {
    PointReason.JOURNAL_CREATED: 10,
    PointReason.DETAIL_FILLED: 5,
    PointReason.FIRST_PLACE: 15,
    PointReason.PERSONAL_BEST: 20,
    PointReason.POST_CREATED: 5,
    PointReason.COMMENT_CREATED: 1,
}
DAILY_CAP: dict[PointReason, int] = {PointReason.POST_CREATED: 3, PointReason.COMMENT_CREATED: 10}
KST = timedelta(hours=9)

EventKey = tuple[PointReason, str]  # (사유, 중복 방지 키)


@dataclass(frozen=True)
class ExpectedEvent:
    delta: int
    journal_id: int | None


def species_key(j: Journal) -> str | None:
    """최대어 비교 단위. 직접 입력 어종은 공백·대소문자를 무시하고 같은 어종으로 본다"""
    if j.species_code:
        return f"code:{j.species_code}"
    if j.species_etc:
        return "etc:" + "".join(j.species_etc.split()).lower()
    return None


def expected_events(journals: list[Journal]) -> dict[EventKey, ExpectedEvent]:
    """일지 목록(출조 일시순)으로 있어야 할 이벤트를 계산한다"""
    events: dict[EventKey, ExpectedEvent] = {}
    seen_places: set[int] = set()
    best_by_species: dict[str, float] = {}

    for j in sorted(journals, key=lambda x: (x.fished_at, x.id)):
        ref = f"journal:{j.id}"
        events[(PointReason.JOURNAL_CREATED, ref)] = ExpectedEvent(POINTS[PointReason.JOURNAL_CREATED], j.id)

        sp = species_key(j)
        if sp and j.max_length_cm:
            events[(PointReason.DETAIL_FILLED, ref)] = ExpectedEvent(POINTS[PointReason.DETAIL_FILLED], j.id)

        # 장소별 가장 이른 일지 1건에 귀속. 그 일지가 빠지면 다음 일지로 넘어간다
        if j.place_id not in seen_places:
            seen_places.add(j.place_id)
            events[(PointReason.FIRST_PLACE, f"place:{j.place_id}")] = ExpectedEvent(
                POINTS[PointReason.FIRST_PLACE], j.id
            )

        # 같은 어종의 직전 최대 길이를 "초과"할 때만. 어종의 첫 기록은 갱신이 아니다 (명세 D-9)
        if sp and j.max_length_cm:
            prev = best_by_species.get(sp)
            if prev is not None and j.max_length_cm > prev:
                events[(PointReason.PERSONAL_BEST, ref)] = ExpectedEvent(
                    POINTS[PointReason.PERSONAL_BEST], j.id
                )
            if prev is None or j.max_length_cm > prev:
                best_by_species[sp] = j.max_length_cm

    return events


def capped_events(reason: PointReason, items: list[tuple[int, object]]) -> dict[EventKey, ExpectedEvent]:
    """글·댓글: (id, 작성 시각) 목록에서 한국 날짜마다 앞의 DAILY_CAP 개만 포인트"""
    out: dict[EventKey, ExpectedEvent] = {}
    per_day: dict[str, int] = defaultdict(int)
    kind = "post" if reason == PointReason.POST_CREATED else "comment"
    for item_id, at in sorted(items, key=lambda x: (x[1], x[0])):
        day = (at + KST).date().isoformat()
        if per_day[day] >= DAILY_CAP[reason]:
            continue
        per_day[day] += 1
        out[(reason, f"{kind}:{item_id}")] = ExpectedEvent(POINTS[reason], None)
    return out


def recompute_points(db: Session, user: AppUser) -> int:
    """원장을 기대 상태에 맞춘다. 반환값 = 이번에 추가된 증감 합계 (flush 만 하고 commit 은 호출자가 한다)"""
    db.flush()  # 세션이 autoflush=False 라서, 방금 바꾼 인증 상태·삭제를 조회에 반영
    journals = list(
        db.scalars(select(Journal).where(Journal.user_id == user.id, Journal.deleted_at.is_(None))).all()
    )
    expected = expected_events(journals)
    posts = db.execute(
        select(Post.id, Post.created_at).where(Post.user_id == user.id, Post.deleted_at.is_(None))
    ).all()
    comments = db.execute(
        select(Comment.id, Comment.created_at).where(Comment.user_id == user.id, Comment.deleted_at.is_(None))
    ).all()
    expected.update(capped_events(PointReason.POST_CREATED, [tuple(r) for r in posts]))
    expected.update(capped_events(PointReason.COMMENT_CREATED, [tuple(r) for r in comments]))

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
