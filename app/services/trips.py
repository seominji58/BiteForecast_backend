"""출조계획 (설계안 docs/05_UX/2026-11-09_출조계획_설계안.md).

- 본인 계획만 보고 바꾼다 (다른 사람 계획은 404 — 있는지조차 알리지 않음)
- 미래 날짜는 예보 범위와 관계없이 저장한다. 해황은 볼 때 계산하고, 예보 범위 밖이면 「예보 발표 전」
- 다른 날짜의 값으로 대신하지 않는다
"""

from collections import Counter
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.timeutil import KST, today_kst
from app.models import AppUser, Journal, Place, PlaceStation, Species, TripChecklistItem, TripPlan, TripStop
from app.models.base import utcnow
from app.schemas.place import PlaceOut
from app.schemas.trip import (
    MAX_ACTIVE_PLANS,
    MAX_AHEAD_DAYS,
    MAX_DAYS,
    MAX_PAST_DAYS,
    MAX_STOPS_PER_DAY,
    ChecklistItemIn,
    ChecklistItemOut,
    StopOutlookOut,
    TripIn,
    TripListItemOut,
    TripOut,
    TripOutlookOut,
    TripPatch,
    TripStopIn,
    TripStopOut,
    TripStopPatch,
)
from app.services import compare as compare_svc
from app.services.freshness import data_status
from app.services.location import coord_states, suspect_place_ids
from app.services.summary import summarize_place

DEFAULT_CHECKLIST = ["낚싯대·릴·채비", "미끼·보냉 장비", "구명조끼", "출발 전 기상특보 재확인"]


def _bad(msg: str) -> HTTPException:
    return HTTPException(status_code=400, detail=msg)


# --- 조회 ---


def _load(db: Session, user: AppUser, trip_id: int) -> TripPlan:
    t = db.scalar(
        select(TripPlan)
        .where(TripPlan.id == trip_id, TripPlan.user_id == user.id, TripPlan.deleted_at.is_(None))
        .options(
            selectinload(TripPlan.stops).selectinload(TripStop.place).selectinload(Place.region),
            selectinload(TripPlan.checklist),
        )
    )
    if t is None:
        raise HTTPException(status_code=404, detail="출조계획을 찾을 수 없습니다")
    return t


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


def to_out(db: Session, t: TripPlan) -> TripOut:
    suspects = suspect_place_ids(db)
    journals = _journal_ids(db, [s.id for s in t.stops])
    species = db.get(Species, t.species_code) if t.species_code else None
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
        stops=[_stop_out(s, suspects, journals, coord_states(db)) for s in t.stops],
        checklist=[ChecklistItemOut.model_validate(c) for c in t.checklist],
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def get_trip(db: Session, user: AppUser, trip_id: int) -> TripOut:
    return to_out(db, _load(db, user, trip_id))


def list_trips(db: Session, user: AppUser, when: str) -> list[TripListItemOut]:
    today = today_kst()
    stmt = (
        select(TripPlan)
        .where(TripPlan.user_id == user.id, TripPlan.deleted_at.is_(None))
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
    suspects = suspect_place_ids(db)
    journals = _journal_ids(db, [s.id for t in plans for s in t.stops])
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
            first_stop=_stop_out(t.stops[0], suspects, journals, coord_states(db)) if t.stops else None,
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
    t.checklist = [
        TripChecklistItem(label=c.label, checked=c.checked, sort_order=i) for i, c in enumerate(items)
    ]
    db.commit()
    db.expire(t)
    return get_trip(db, user, t.id)


def owned_stop_for_journal(db: Session, user: AppUser, stop_id: int, place_id: int) -> None:
    """기록에 계획 장소를 연결할 때: 본인 계획의 장소이고 같은 낚시터여야 한다"""
    s = db.scalar(
        select(TripStop)
        .join(TripPlan, TripPlan.id == TripStop.plan_id)
        .where(TripStop.id == stop_id, TripPlan.user_id == user.id, TripPlan.deleted_at.is_(None))
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
    t = _load(db, user, trip_id)
    today = today_kst()
    ds = data_status(db)
    last = forecast_last_day(ds.forecast_valid_until)
    rng = compare_svc.date_range()
    suspects = suspect_place_ids(db)
    out: list[StopOutlookOut] = []
    for s in t.stops:
        base = {"stop_id": s.id, "day": s.day, "place_id": s.place_id}
        if s.place_id in suspects:
            out.append(StopOutlookOut(**base, forecast_status="location_check"))
            continue
        if s.day < today:
            out.append(StopOutlookOut(**base, forecast_status="past"))
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
                warning_level=sm.warning_level,
                warning_types=sm.warning_types,
                warning_is_current=s.day == today,
                tides=sm.tides,
            )
        )
    return TripOutlookOut(trip_id=t.id, today=today, forecast_last_day=last, stops=out, data_status=ds)
