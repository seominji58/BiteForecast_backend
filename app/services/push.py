"""알림 규칙 (2026-11-25). 수집기가 매시간 돈 뒤 부른다.

1. fav_good     : 저녁(18~20시)에, 내일 즐겨찾기 낚시터의 공식 지수가 「좋음」 이상이면 하루 한 번
2. trip_warning : 낮(7~21시)에, 오늘·내일 출조지에 해상 특보(warning 등급)가 걸리면
                  계획·날짜·특보 종류마다 한 번
3. weekly_best  : 월요일 아침(8~10시)에, 앞으로 7일 중 즐겨찾기가 가장 좋은 날 (좋음 이상일 때만) 주 한 번

- 시간 범위를 몇 시간으로 둔 건 수집기가 가끔 한두 시간 건너뛰어도 놓치지 않게. 중복은 push_log 로 막는다
- 지수는 국립해양조사원 발표값 그대로 (그날 어느 어종·시간대든 가장 좋은 등급). 앱 화면과 같은 기준
- 밤에는 보내지 않는다
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Favorite,
    FishingIndex,
    Place,
    PlaceStation,
    PushDevice,
    PushLog,
    PushPref,
    TripMember,
    TripPlan,
    TripStop,
)
from app.models.enums import StationRole
from app.services import fcm, warning

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
RANK = {"매우좋음": 5, "좋음": 4, "보통": 3, "나쁨": 2, "매우나쁨": 1}
GOOD = 4
WEEKDAY = "월화수목금토일"


def _md(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAY[d.weekday()]})"


def _names(names: list[str], n: int = 2) -> str:
    head = "·".join(names[:n])
    return head + (f" 외 {len(names) - n}곳" if len(names) > n else "")


def _wants(db: Session, kind: str) -> dict[int, list[str]]:
    """이 알림을 켠 사용자 → 폰 토큰들 (설정 줄이 없으면 켜진 것)"""
    col = getattr(PushPref, kind)
    rows = db.execute(
        select(PushDevice.user_id, PushDevice.token)
        .outerjoin(PushPref, PushPref.user_id == PushDevice.user_id)
        .where(or_(PushPref.user_id.is_(None), col.is_(True)))
    ).all()
    out: dict[int, list[str]] = defaultdict(list)
    for uid, tok in rows:
        out[uid].append(tok)
    return out


def _grades(db: Session, place_ids: set[int], days: list[date]) -> dict[tuple[int, date], int]:
    """(낚시터, 날짜) → 그날 가장 좋은 공식 지수 등급 (가까운 지수 지점, max_km 이내)"""
    if not place_ids:
        return {}
    links = db.execute(
        select(PlaceStation.place_id, PlaceStation.station_id).where(
            PlaceStation.role == StationRole.FISHING_INDEX,
            PlaceStation.place_id.in_(place_ids),
            PlaceStation.distance_km <= get_settings().fishing_index_max_km,
        )
    ).all()
    by_station: dict[int, list[int]] = defaultdict(list)
    for pid, sid in links:
        by_station[sid].append(pid)
    out: dict[tuple[int, date], int] = {}
    if not by_station:
        return out
    for sid, day, idx in db.execute(
        select(FishingIndex.station_id, FishingIndex.day, FishingIndex.index).where(
            FishingIndex.station_id.in_(by_station),
            FishingIndex.day.in_(days),
            FishingIndex.index.is_not(None),
        )
    ):
        r = RANK.get(idx, 0)
        for pid in by_station[sid]:
            if r > out.get((pid, day), 0):
                out[(pid, day)] = r
    return out


def _favorites(db: Session, user_ids) -> dict[int, list[Place]]:
    out: dict[int, list[Place]] = defaultdict(list)
    for uid, place in db.execute(
        select(Favorite.user_id, Place)
        .join(Place, Place.id == Favorite.place_id)
        .where(Favorite.user_id.in_(list(user_ids)), Place.is_active.is_(True))
        .order_by(Favorite.created_at)
    ):
        out[uid].append(place)
    return out


def _claim(db: Session, uid: int, kind: str, key: str) -> bool:
    """처음 보내는 알림이면 기록하고 True (이미 보냈으면 False)"""
    if db.scalar(select(PushLog.id).where(PushLog.user_id == uid, PushLog.kind == kind, PushLog.key == key)):
        return False
    try:
        with db.begin_nested():
            db.add(PushLog(user_id=uid, kind=kind, key=key))
    except IntegrityError:
        return False
    return True


def plan_fav_good(db: Session, now: datetime) -> list[tuple[int, str, str, fcm.Message]]:
    if not 18 <= now.hour <= 20:
        return []
    tomorrow = now.date() + timedelta(days=1)
    users = _wants(db, "fav_good")
    favs = _favorites(db, users)
    grades = _grades(db, {p.id for ps in favs.values() for p in ps}, [tomorrow])
    out = []
    for uid, places in favs.items():
        good = [p for p in places if grades.get((p.id, tomorrow), 0) >= GOOD]
        if not good:
            continue
        best = max(good, key=lambda p: grades[(p.id, tomorrow)])
        msg = fcm.Message(
            title=f"내일 {_names([p.name for p in good])} 「좋음」",
            body=(
                f"{_md(tomorrow)} 즐겨찾기 낚시터의 바다낚시지수가 좋아요. "
                "출발 전 특보·해황을 꼭 확인하세요."
            ),
            data={"url": f"/place/{best.id}" if len(good) == 1 else "/"},
        )
        out.append((uid, "fav_good", tomorrow.isoformat(), msg))
    return out


def plan_weekly_best(db: Session, now: datetime) -> list[tuple[int, str, str, fcm.Message]]:
    if now.weekday() != 0 or not 8 <= now.hour <= 10:
        return []
    days = [now.date() + timedelta(days=i) for i in range(7)]
    users = _wants(db, "weekly_best")
    favs = _favorites(db, users)
    grades = _grades(db, {p.id for ps in favs.values() for p in ps}, days)
    year, week, _ = now.date().isocalendar()
    out = []
    for uid, places in favs.items():
        # 좋음 이상인 즐겨찾기가 가장 많은 날 (같으면 등급 합, 그다음 빠른 날)
        scored = []
        for d in days:
            good = [p for p in places if grades.get((p.id, d), 0) >= GOOD]
            if good:
                scored.append((len(good), sum(grades[(p.id, d)] for p in good), -d.toordinal(), d, good))
        if not scored:
            continue
        *_, d, good = max(scored, key=lambda s: s[:3])
        msg = fcm.Message(
            title=f"이번 주는 {_md(d)}이 가장 좋아요",
            body=(
                f"{_names([p.name for p in good])} 바다낚시지수 「좋음」 이상이에요. "
                "가까워지면 예보가 바뀔 수 있어요."
            ),
            data={"url": "/trips"},
        )
        out.append((uid, "weekly_best", f"{year}-W{week:02d}", msg))
    return out


def plan_trip_warning(db: Session, now: datetime) -> list[tuple[int, str, str, fcm.Message]]:
    if not 7 <= now.hour <= 21:
        return []
    today = now.date()
    days = [today, today + timedelta(days=1)]
    users = _wants(db, "trip_warning")
    if not users:
        return []
    stops = db.execute(
        select(TripPlan, TripStop.day, Place)
        .join(TripStop, TripStop.plan_id == TripPlan.id)
        .join(Place, Place.id == TripStop.place_id)
        .where(TripPlan.deleted_at.is_(None), TripStop.day.in_(days))
        .order_by(TripStop.day, TripStop.sort_order)
    ).all()
    if not stops:
        return []
    snap = warning.latest_snapshot(db)
    health = warning.collection_health(snap.fetched_at if snap else None)
    hits: dict[tuple[int, date], tuple[TripPlan, set[str], list[str]]] = {}
    for plan, day, place in stops:
        w = warning.evaluate(db, place, snap, health)
        if w.level != "warning":
            continue
        _, types, names = hits.setdefault((plan.id, day), (plan, set(), []))
        types.update(m.type for m in w.active if m.severe)
        if place.name not in names:
            names.append(place.name)
    if not hits:
        return []
    plan_ids = {pid for pid, _ in hits}
    members: dict[int, set[int]] = defaultdict(set)
    for pid, uid in db.execute(
        select(TripMember.plan_id, TripMember.user_id).where(
            TripMember.plan_id.in_(plan_ids), TripMember.status == "joined"
        )
    ):
        members[pid].add(uid)
    out = []
    for (pid, day), (plan, types, names) in hits.items():
        when = "오늘" if day == today else "내일"
        kinds = "·".join(sorted(types)) or "해상 특보"
        msg = fcm.Message(
            title=f"{when} 출조지에 {kinds}",
            body=f"「{plan.title}」 {_names(names)}에 특보가 발효 중이에요. 출조 여부를 다시 확인하세요.",
            data={"url": f"/trip/{pid}"},
        )
        for uid in {plan.user_id} | members[pid]:
            if uid in users:
                out.append((uid, "trip_warning", f"{pid}:{day.isoformat()}:{kinds}"[:120], msg))
    return out


def run(db: Session, now: datetime | None = None) -> dict[str, int]:
    """알림 대상을 찾아 보낸다. 키가 없으면(로컬·테스트) 대상만 세고 보내지 않는다"""
    now = (now or datetime.now(KST)).astimezone(KST)
    stats: dict[str, int] = defaultdict(int)
    plans = plan_trip_warning(db, now) + plan_fav_good(db, now) + plan_weekly_best(db, now)
    if not plans:
        return dict(stats)
    users = {uid for uid, *_ in plans}
    tokens: dict[int, list[str]] = defaultdict(list)
    for uid, tok in db.execute(
        select(PushDevice.user_id, PushDevice.token).where(PushDevice.user_id.in_(users))
    ):
        tokens[uid].append(tok)
    dead: list[str] = []
    for uid, kind, key, msg in plans:
        stats[f"{kind}_due"] += 1
        if not fcm.enabled() or not _claim(db, uid, kind, key):
            continue
        db.commit()  # 보내기 전에 기록 — 실패해도 같은 알림을 매시간 다시 보내지 않게
        sent, gone = fcm.send(tokens[uid], msg)
        stats[f"{kind}_sent"] += sent
        dead += gone
    if dead:
        db.query(PushDevice).filter(PushDevice.token.in_(dead)).delete(synchronize_session=False)
        stats["dead_tokens"] = len(dead)
    db.commit()
    return dict(stats)
