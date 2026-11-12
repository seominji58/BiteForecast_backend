"""출조계획 (설계안 docs/05_UX/2026-11-09_출조계획_설계안.md).

- 본인 계획만 보고 바꾼다 (다른 사람 계획은 404 — 있는지조차 알리지 않음)
- 미래 날짜는 예보 범위와 관계없이 저장한다. 해황은 볼 때 계산하고, 예보 범위 밖이면 「예보 발표 전」
- 다른 날짜의 값으로 대신하지 않는다
"""

import secrets
from collections import Counter
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.timeutil import KST, today_kst
from app.models import (
    AppUser,
    Journal,
    Place,
    PlaceStation,
    Species,
    TripChecklistItem,
    TripInvite,
    TripMember,
    TripPlan,
    TripStop,
)
from app.models.base import utcnow
from app.schemas.place import PlaceOut
from app.schemas.trip import (
    INVITE_DAYS,
    MAX_ACTIVE_PLANS,
    MAX_AHEAD_DAYS,
    MAX_DAYS,
    MAX_MEMBERS,
    MAX_PAST_DAYS,
    MAX_STOPS_PER_DAY,
    ChecklistItemIn,
    ChecklistItemOut,
    ChecklistItemPatch,
    InviteOut,
    InvitePreviewOut,
    MemberStatus,
    StopOutlookOut,
    TripIn,
    TripListItemOut,
    TripMemberOut,
    TripOut,
    TripOutlookOut,
    TripPatch,
    TripStopIn,
    TripStopOut,
    TripStopPatch,
)
from app.services import compare as compare_svc
from app.services.community import nicknames
from app.services.compare import reference_warning
from app.services.freshness import data_status
from app.services.location import location_ctx
from app.services.summary import summarize_place

DEFAULT_CHECKLIST = ["낚싯대·릴·채비", "미끼·보냉 장비", "구명조끼", "출발 전 기상특보 재확인"]


def _bad(msg: str) -> HTTPException:
    return HTTPException(status_code=400, detail=msg)


# --- 조회 ---


ACTIVE_STATUSES = ("joined", "maybe")  # 참여·미정 = 함께 가는 사람 (불참은 목록에서 뺀다)


def _member(db: Session, plan_id: int, user_id: int) -> TripMember | None:
    return db.scalar(select(TripMember).where(TripMember.plan_id == plan_id, TripMember.user_id == user_id))


def _load(db: Session, user: AppUser, trip_id: int, *, owner: bool = True) -> TripPlan:
    """owner=True: 만든 사람만 (계획·장소 수정). owner=False: 참여자도 볼 수 있다"""
    t = db.scalar(
        select(TripPlan)
        .where(TripPlan.id == trip_id, TripPlan.deleted_at.is_(None))
        .options(
            selectinload(TripPlan.stops).selectinload(TripStop.place).selectinload(Place.region),
            selectinload(TripPlan.checklist),
        )
    )
    if t is None:
        raise HTTPException(status_code=404, detail="출조계획을 찾을 수 없습니다")
    if t.user_id == user.id:
        return t
    m = _member(db, t.id, user.id)
    if m is None:
        # 다른 사람의 계획은 있는지도 알려주지 않는다
        raise HTTPException(status_code=404, detail="출조계획을 찾을 수 없습니다")
    if owner:
        raise HTTPException(status_code=403, detail="계획을 만든 사람만 바꿀 수 있어요")
    return t


def _participants(db: Session, t: TripPlan) -> set[int]:
    """만든 사람 + 참여·미정 참여자"""
    ids = {t.user_id}
    ids.update(
        db.scalars(
            select(TripMember.user_id).where(
                TripMember.plan_id == t.id, TripMember.status.in_(ACTIVE_STATUSES)
            )
        )
    )
    return ids


def _journal_ids(db: Session, stop_ids: list[int]) -> dict[int, list[int]]:
    if not stop_ids:
        return {}
    rows = db.execute(
        select(Journal.trip_stop_id, Journal.id)
        .where(Journal.trip_stop_id.in_(stop_ids), Journal.deleted_at.is_(None))
        .order_by(Journal.id)
    ).all()
    out: dict[int, list[int]] = {}
    for sid, jid in rows:
        out.setdefault(sid, []).append(jid)
    return out


def _stop_out(
    s: TripStop, suspects: frozenset[int], journals: dict[int, list[int]], coords: dict | None = None
) -> TripStopOut:
    place = PlaceOut.model_validate(s.place).model_copy(
        update={"location_suspect": s.place_id in suspects, "coord": (coords or {}).get(s.place_id)}
    )
    return TripStopOut(
        id=s.id,
        day=s.day,
        place=place,
        role=s.role,  # type: ignore[arg-type]
        sort_order=s.sort_order,
        start_time=s.start_time,
        end_time=s.end_time,
        memo=s.memo,
        journal_ids=journals.get(s.id, []),
    )


def to_out(db: Session, t: TripPlan, user: AppUser | None = None) -> TripOut:
    loc = location_ctx(db)  # 위치 판단은 한 번만 읽는다 (장소마다 다시 읽지 않음)
    journals = _journal_ids(db, [s.id for s in t.stops])
    species = db.get(Species, t.species_code) if t.species_code else None
    rows = db.execute(
        select(TripMember.user_id, TripMember.status)
        .where(TripMember.plan_id == t.id)
        .order_by(TripMember.id)
    ).all()
    order = {"joined": 0, "maybe": 1, "declined": 2}
    people = [(t.user_id, "joined"), *sorted(((u, st) for u, st in rows), key=lambda x: order.get(x[1], 9))]
    assignees = {c.assignee_user_id for c in t.checklist if c.assignee_user_id}
    names = nicknames(db, {u for u, _ in people} | assignees)
    return TripOut(
        id=t.id,
        title=t.title,
        start_date=t.start_date,
        end_date=t.end_date,
        region=t.region,
        species_code=t.species_code,
        species_name=species.name_ko if species else None,
        species_etc=t.species_etc,
        memo=t.memo,
        stops=[_stop_out(s, loc.suspects, journals, loc.coords) for s in t.stops],
        checklist=[
            ChecklistItemOut.model_validate(c).model_copy(
                update={"assignee_nickname": names.get(c.assignee_user_id) if c.assignee_user_id else None}
            )
            for c in t.checklist
        ],
        created_at=t.created_at,
        updated_at=t.updated_at,
        my_role="owner" if user is None or user.id == t.user_id else "member",
        members=[
            TripMemberOut(
                user_id=uid,
                nickname=names[uid],
                role="owner" if uid == t.user_id else "member",
                status=status,
                mine=user is not None and uid == user.id,
            )
            for uid, status in people
        ],
    )


def get_trip(db: Session, user: AppUser, trip_id: int) -> TripOut:
    return to_out(db, _load(db, user, trip_id, owner=False), user)


def list_trips(db: Session, user: AppUser, when: str) -> list[TripListItemOut]:
    today = today_kst()
    stmt = (
        select(TripPlan)
        .where(
            (TripPlan.user_id == user.id)
            | TripPlan.id.in_(
                select(TripMember.plan_id).where(
                    TripMember.user_id == user.id, TripMember.status.in_(ACTIVE_STATUSES)
                )
            ),
            TripPlan.deleted_at.is_(None),
        )
        .options(
            selectinload(TripPlan.stops).selectinload(TripStop.place).selectinload(Place.region),
            selectinload(TripPlan.checklist),
        )
    )
    if when == "past":
        stmt = stmt.where(TripPlan.end_date < today).order_by(TripPlan.start_date.desc(), TripPlan.id.desc())
    else:
        stmt = stmt.where(TripPlan.end_date >= today).order_by(TripPlan.start_date, TripPlan.id)
    plans = db.scalars(stmt).all()
    loc = location_ctx(db)
    journals = _journal_ids(db, [s.id for t in plans for s in t.stops])
    counts = dict(
        db.execute(
            select(TripMember.plan_id, func.count())
            .where(TripMember.plan_id.in_([t.id for t in plans]), TripMember.status.in_(ACTIVE_STATUSES))
            .group_by(TripMember.plan_id)
        ).all()
    ) if plans else {}
    return [
        TripListItemOut(
            id=t.id,
            title=t.title,
            start_date=t.start_date,
            end_date=t.end_date,
            region=t.region,
            stop_count=len(t.stops),
            checklist_done=sum(c.checked for c in t.checklist),
            checklist_total=len(t.checklist),
            journal_count=sum(len(journals.get(s.id, [])) for s in t.stops),
            first_stop=_stop_out(t.stops[0], loc.suspects, journals, loc.coords) if t.stops else None,
            my_role="owner" if t.user_id == user.id else "member",
            member_count=1 + counts.get(t.id, 0),
        )
        for t in plans
    ]


# --- 검증 ---


def _check_dates(start: date, end: date) -> None:
    today = today_kst()
    if end < start:
        raise _bad("끝 날짜가 시작 날짜보다 빠릅니다")
    if (end - start).days + 1 > MAX_DAYS:
        raise _bad(f"계획 기간은 최대 {MAX_DAYS}일입니다")
    if start < today - timedelta(days=MAX_PAST_DAYS):
        raise _bad(f"지난 출조는 {MAX_PAST_DAYS}일 이내만 계획으로 남길 수 있습니다")
    if end > today + timedelta(days=MAX_AHEAD_DAYS):
        raise _bad("1년 넘게 앞선 날짜는 계획할 수 없습니다")


def _check_species(db: Session, code: str | None) -> None:
    if code and db.get(Species, code) is None:
        raise _bad("알 수 없는 어종 코드입니다")


def _check_place(db: Session, place_id: int) -> None:
    p = db.get(Place, place_id)
    if p is None or not p.is_active:
        raise _bad("지원하지 않는 장소입니다")


def _check_stop(t: TripPlan, day: date, start, end, ignore_id: int | None = None) -> None:
    if not (t.start_date <= day <= t.end_date):
        raise _bad("장소 날짜가 계획 기간 밖입니다")
    if start and end and end < start:
        raise _bad("끝 시간이 시작 시간보다 빠릅니다")
    same_day = [s for s in t.stops if s.day == day and s.id != ignore_id]
    if len(same_day) >= MAX_STOPS_PER_DAY:
        raise _bad(f"하루에 장소는 최대 {MAX_STOPS_PER_DAY}곳입니다")


def _auto_title(db: Session, data: TripIn) -> str:
    d = data.start_date
    where = data.region
    if not where and data.stops:
        place = db.get(Place, data.stops[0].place_id)
        where = place.region.name.split()[-1] if place and place.region else None
    return f"{d.month}/{d.day} {where + ' ' if where else ''}출조"[:60]


# --- 쓰기 ---


def create_trip(db: Session, user: AppUser, data: TripIn) -> TripOut:
    active = db.scalar(
        select(func.count(TripPlan.id)).where(TripPlan.user_id == user.id, TripPlan.deleted_at.is_(None))
    )
    if (active or 0) >= MAX_ACTIVE_PLANS:
        raise _bad(f"출조계획은 최대 {MAX_ACTIVE_PLANS}개까지 둘 수 있습니다. 지난 계획을 지워 주세요")
    _check_dates(data.start_date, data.end_date)
    _check_species(db, data.species_code)
    per_day = Counter(s.day for s in data.stops)
    for s in data.stops:
        _check_place(db, s.place_id)
        if not (data.start_date <= s.day <= data.end_date):
            raise _bad("장소 날짜가 계획 기간 밖입니다")
        if s.start_time and s.end_time and s.end_time < s.start_time:
            raise _bad("끝 시간이 시작 시간보다 빠릅니다")
    if per_day and max(per_day.values()) > MAX_STOPS_PER_DAY:
        raise _bad(f"하루에 장소는 최대 {MAX_STOPS_PER_DAY}곳입니다")

    t = TripPlan(
        user_id=user.id,
        title=data.title or _auto_title(db, data),
        **data.model_dump(
            include={"start_date", "end_date", "region", "species_code", "species_etc", "memo"}
        ),
    )
    order = Counter()
    for s in data.stops:
        t.stops.append(TripStop(**s.model_dump(), sort_order=order[s.day]))
        order[s.day] += 1
    items = (
        data.checklist
        if data.checklist is not None
        else [ChecklistItemIn(label=x) for x in DEFAULT_CHECKLIST]
    )
    t.checklist = [
        TripChecklistItem(label=c.label, checked=c.checked, sort_order=i) for i, c in enumerate(items)
    ]
    db.add(t)
    db.commit()
    return get_trip(db, user, t.id)


def update_trip(db: Session, user: AppUser, trip_id: int, data: TripPatch) -> TripOut:
    t = _load(db, user, trip_id)
    values = data.model_dump(exclude_unset=True)
    if "title" in values and not values["title"]:
        raise _bad("제목을 입력해 주세요")
    start = values.get("start_date") or t.start_date
    end = values.get("end_date") or t.end_date
    if "start_date" in values or "end_date" in values:
        _check_dates(start, end)
        outside = [s for s in t.stops if not (start <= s.day <= end)]
        if outside:
            names = ", ".join(f"{s.day.month}/{s.day.day} {s.place.name}" for s in outside)
            raise _bad(f"바꾼 기간 밖에 있는 장소가 있습니다: {names}. 장소를 먼저 옮기거나 지워 주세요")
    _check_species(db, values.get("species_code"))
    values.pop("start_date", None)
    values.pop("end_date", None)
    t.start_date, t.end_date = start, end
    for k, v in values.items():
        setattr(t, k, v)
    db.commit()
    return get_trip(db, user, t.id)


def delete_trip(db: Session, user: AppUser, trip_id: int) -> None:
    t = _load(db, user, trip_id)
    t.deleted_at = utcnow()
    db.commit()


def add_stop(db: Session, user: AppUser, trip_id: int, data: TripStopIn) -> TripOut:
    t = _load(db, user, trip_id)
    _check_place(db, data.place_id)
    _check_stop(t, data.day, data.start_time, data.end_time)
    order = max((s.sort_order for s in t.stops if s.day == data.day), default=-1) + 1
    t.stops.append(TripStop(**data.model_dump(), sort_order=order))
    db.commit()
    db.expire(t)
    return get_trip(db, user, t.id)


def _owned_stop(t: TripPlan, stop_id: int) -> TripStop:
    s = next((x for x in t.stops if x.id == stop_id), None)
    if s is None:
        raise HTTPException(status_code=404, detail="계획의 장소를 찾을 수 없습니다")
    return s


def update_stop(db: Session, user: AppUser, trip_id: int, stop_id: int, data: TripStopPatch) -> TripOut:
    t = _load(db, user, trip_id)
    s = _owned_stop(t, stop_id)
    values = data.model_dump(exclude_unset=True)
    if values.get("place_id") is not None:
        _check_place(db, values["place_id"])
    day = values.get("day") or s.day
    start = values["start_time"] if "start_time" in values else s.start_time
    end = values["end_time"] if "end_time" in values else s.end_time
    _check_stop(t, day, start, end, ignore_id=s.id)
    for k, v in values.items():
        if v is None and k in ("day", "place_id", "role", "sort_order"):
            continue  # 필수 칸은 null 로 지우지 않는다
        setattr(s, k, v)
    db.commit()
    db.expire(t)
    return get_trip(db, user, t.id)


def delete_stop(db: Session, user: AppUser, trip_id: int, stop_id: int) -> TripOut:
    t = _load(db, user, trip_id)
    s = _owned_stop(t, stop_id)
    for j in db.scalars(select(Journal).where(Journal.trip_stop_id == s.id)):
        j.trip_stop_id = None  # 기록은 남기고 연결만 끊는다
    t.stops.remove(s)
    db.commit()
    db.expire(t)
    return get_trip(db, user, t.id)


def replace_checklist(db: Session, user: AppUser, trip_id: int, items: list[ChecklistItemIn]) -> TripOut:
    t = _load(db, user, trip_id)
    people = _participants(db, t)
    for c in items:
        if c.assignee_user_id is not None and c.assignee_user_id not in people:
            raise _bad("담당자는 함께 가는 사람 중에서 정해 주세요")
    t.checklist = [
        TripChecklistItem(label=c.label, checked=c.checked, sort_order=i, assignee_user_id=c.assignee_user_id)
        for i, c in enumerate(items)
    ]
    db.commit()
    db.expire(t)
    return get_trip(db, user, t.id)


def owned_stop_for_journal(db: Session, user: AppUser, stop_id: int, place_id: int) -> None:
    """기록에 계획 장소를 연결할 때: 내가 만들었거나 함께 가는 계획의 장소이고 같은 낚시터여야 한다"""
    s = db.scalar(
        select(TripStop)
        .join(TripPlan, TripPlan.id == TripStop.plan_id)
        .where(
            TripStop.id == stop_id,
            TripPlan.deleted_at.is_(None),
            (TripPlan.user_id == user.id)
            | TripPlan.id.in_(
                select(TripMember.plan_id).where(
                    TripMember.user_id == user.id, TripMember.status.in_(ACTIVE_STATUSES)
                )
            ),
        )
    )
    if s is None:
        raise _bad("연결할 출조계획 장소를 찾을 수 없습니다")
    if s.place_id != place_id:
        raise _bad("출조계획 장소와 기록 장소가 다릅니다")


# --- 해황 ---


def forecast_last_day(valid_until) -> date | None:
    """받아 둔 예보가 하루 전체를 덮는 마지막 날짜 (KST). valid_until 이 KST 자정이면 그 전날"""
    if valid_until is None:
        return None
    return (valid_until - timedelta(seconds=1)).astimezone(KST).date()


def outlook(db: Session, user: AppUser, trip_id: int) -> TripOutlookOut:
    t = _load(db, user, trip_id, owner=False)
    today = today_kst()
    ds = data_status(db)
    last = forecast_last_day(ds.forecast_valid_until)
    rng = compare_svc.date_range()
    loc = location_ctx(db)
    suspects, holds = loc.suspects, loc.holds
    out: list[StopOutlookOut] = []
    for s in t.stops:
        base = {"stop_id": s.id, "day": s.day, "place_id": s.place_id}
        if s.place_id in suspects:
            out.append(StopOutlookOut(**base, forecast_status="location_check"))
            continue
        if s.day < today:
            out.append(StopOutlookOut(**base, forecast_status="past"))
            continue
        if s.place_id in holds:
            # 좌표 기준 자료는 판단 보류. 특보는 주소 기준(오늘이면 지금 발효 상태)만
            w = reference_warning(db, s.place)
            out.append(
                StopOutlookOut(
                    **base,
                    forecast_status="location_review",
                    warning_level=w.level,
                    warning_types=sorted({m.type for m in w.active}),
                    warning_is_current=s.day == today,
                    warning_note=w.note,
                )
            )
            continue
        pending = last is None or s.day > last
        if s.day > rng.max:
            # 조석 예측도 받아 두지 않은 날짜 — 계산할 자료가 없다
            out.append(StopOutlookOut(**base, forecast_status="pending"))
            continue
        place = db.scalar(
            select(Place)
            .where(Place.id == s.place_id)
            .options(
                selectinload(Place.region), selectinload(Place.stations).selectinload(PlaceStation.station)
            )
        )
        sm = summarize_place(db, place, s.day)
        out.append(
            StopOutlookOut(
                **base,
                forecast_status="pending" if pending else "available",
                # 예보 범위 밖이면 일부만 있는 값(예: 다음 날 00시 한 점)도 쓰지 않는다
                wave_fc_max=None if pending else sm.wave_fc_max,
                wind_fc_max=None if pending else sm.wind_fc_max,
                air_temp_fc_min=None if pending else sm.air_temp_fc_min,
                air_temp_fc_max=None if pending else sm.air_temp_fc_max,
                pop_fc_max=None if pending else sm.pop_fc_max,
                precipitation_types=[] if pending else sm.precipitation_types,
                warning_level=sm.warning_level,
                warning_types=sm.warning_types,
                warning_is_current=s.day == today,
                tides=sm.tides,
            )
        )
    return TripOutlookOut(trip_id=t.id, today=today, forecast_last_day=last, stops=out, data_status=ds)


# --- 함께 가기 (초대·참여) ---

_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 헷갈리는 0·O·1·I 제외


def _new_code(db: Session) -> str:
    while True:
        code = "".join(secrets.choice(_CODE_CHARS) for _ in range(6))
        if db.scalar(select(TripInvite.id).where(TripInvite.code == code)) is None:
            return code


def _usable(i: TripInvite | None) -> bool:
    return i is not None and i.revoked_at is None and i.expires_at > utcnow()


def create_invite(db: Session, user: AppUser, trip_id: int) -> InviteOut:
    """초대 코드 (만든 사람만). 쓸 수 있는 코드가 있으면 그대로 돌려준다"""
    t = _load(db, user, trip_id)
    current = db.scalar(
        select(TripInvite).where(TripInvite.plan_id == t.id).order_by(TripInvite.id.desc()).limit(1)
    )
    if not _usable(current):
        expires = utcnow() + timedelta(days=INVITE_DAYS)
        current = TripInvite(plan_id=t.id, code=_new_code(db), expires_at=expires)
        db.add(current)
        db.commit()
    return InviteOut(code=current.code, expires_at=current.expires_at)


def revoke_invite(db: Session, user: AppUser, trip_id: int) -> None:
    t = _load(db, user, trip_id)
    now = utcnow()
    active = select(TripInvite).where(TripInvite.plan_id == t.id, TripInvite.revoked_at.is_(None))
    for i in db.scalars(active):
        i.revoked_at = now
    db.commit()


def _invite_plan(db: Session, code: str) -> TripPlan:
    i = db.scalar(select(TripInvite).where(TripInvite.code == code.strip().upper()))
    t = db.get(TripPlan, i.plan_id) if _usable(i) else None
    if t is None or t.deleted_at is not None:
        raise HTTPException(
            status_code=404,
            detail="초대 코드가 없거나 만료됐어요. 계획을 만든 사람에게 새 코드를 받아 주세요",
        )
    return t


def preview_invite(db: Session, user: AppUser, code: str) -> InvitePreviewOut:
    t = _invite_plan(db, code)
    people = _participants(db, t)
    return InvitePreviewOut(
        trip_id=t.id,
        title=t.title,
        start_date=t.start_date,
        end_date=t.end_date,
        owner_nickname=nicknames(db, {t.user_id})[t.user_id],
        member_count=len(people),
        already=user.id in people,
    )


def join_trip(db: Session, user: AppUser, code: str) -> TripOut:
    t = _invite_plan(db, code)
    if t.user_id != user.id:
        m = _member(db, t.id, user.id)
        if m is None:
            if len(_participants(db, t)) - 1 >= MAX_MEMBERS:
                raise _bad(f"함께 가는 사람은 최대 {MAX_MEMBERS}명까지예요")
            db.add(TripMember(plan_id=t.id, user_id=user.id, status="joined"))
        else:
            m.status = "joined"
        db.commit()
    return get_trip(db, user, t.id)


def set_my_status(db: Session, user: AppUser, trip_id: int, status: MemberStatus) -> TripOut:
    t = _load(db, user, trip_id, owner=False)
    m = _member(db, t.id, user.id)
    if m is None:
        raise _bad("계획을 만든 사람은 참여 상태를 바꿀 수 없어요")
    m.status = status
    if status == "declined":
        _unassign(db, t, user.id)
    db.commit()
    return get_trip(db, user, t.id)


def _unassign(db: Session, t: TripPlan, user_id: int) -> None:
    for c in t.checklist:
        if c.assignee_user_id == user_id:
            c.assignee_user_id = None


def remove_member(db: Session, user: AppUser, trip_id: int, member_user_id: int) -> None:
    """만든 사람은 누구든 내보낼 수 있고, 참여자는 자기만 나갈 수 있다"""
    t = _load(db, user, trip_id, owner=False)
    if user.id != t.user_id and member_user_id != user.id:
        raise HTTPException(status_code=403, detail="다른 참여자는 만든 사람만 내보낼 수 있어요")
    m = _member(db, t.id, member_user_id)
    if m is None:
        raise HTTPException(status_code=404, detail="참여자를 찾을 수 없습니다")
    _unassign(db, t, member_user_id)
    db.delete(m)
    db.commit()


def patch_checklist_item(
    db: Session, user: AppUser, trip_id: int, item_id: int, data: ChecklistItemPatch
) -> TripOut:
    """준비물 하나 체크·담당. 참여자는 자기 자신만 담당으로 정하거나 자기 담당을 내려놓을 수 있다"""
    t = _load(db, user, trip_id, owner=False)
    c = next((x for x in t.checklist if x.id == item_id), None)
    if c is None:
        raise HTTPException(status_code=404, detail="준비물을 찾을 수 없습니다")
    values = data.model_dump(exclude_unset=True)
    if values.get("checked") is not None:
        c.checked = values["checked"]
    if "assignee_user_id" in values:
        who = values["assignee_user_id"]
        owner = user.id == t.user_id
        if who is not None and who not in _participants(db, t):
            raise _bad("담당자는 함께 가는 사람 중에서 정해 주세요")
        if not owner and who not in (None, user.id):
            raise HTTPException(status_code=403, detail="담당은 자기 자신만 맡을 수 있어요")
        if not owner and who is None and c.assignee_user_id not in (None, user.id):
            raise HTTPException(status_code=403, detail="다른 사람의 담당은 만든 사람만 바꿀 수 있어요")
        c.assignee_user_id = who
    db.commit()
    db.expire(t)
    return get_trip(db, user, t.id)
