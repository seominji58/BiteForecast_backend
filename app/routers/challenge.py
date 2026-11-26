"""전국 낚시 탐험 — 도장 (2026-11-26, 시즌 1: 공식 바다낚시공원).

- 장소 목록: seeds/challenge_spots.json (운영 DB 낚시터 id)
- 도장 찍기: 지금 위치가 장소 반경(300m) 안일 때만. 위치는 확인에만 쓰고 저장하지 않는다(거리 구간만)
- 막는 조건: 그 장소 해상 특보(warning 등급) · 해진 뒤~해뜨기 전 · 같은 곳 하루 1번
- 포인트: 장소마다 처음 방문 +20 (services/points.py 재계산)
"""

import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Reader
from app.core.geo import haversine_km
from app.models import ChallengeVisit, Place
from app.models.base import utcnow
from app.services import warning
from app.services.points import recompute_points
from app.services.sea_calendar import sun_times

router = APIRouter(tags=["challenge"])
_FILE = Path(__file__).resolve().parent.parent.parent / "seeds" / "challenge_spots.json"
KST = ZoneInfo("Asia/Seoul")


@lru_cache(maxsize=1)
def season() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"season": 1, "title": "", "radius_m": 300, "points": 20, "spots": []}


class SpotInfo(BaseModel):
    status: str | None = None
    fee: str | None = None
    hours: str | None = None
    closed: str | None = None
    reservation: str | None = None
    phone: str | None = None
    url: str | None = None
    note: str | None = None
    checked_at: str | None = None


class SpotOut(BaseModel):
    place_id: int
    name: str
    region: str
    sea: str
    lat: float | None
    lon: float | None
    info: SpotInfo | None = None
    visited_at: datetime | None = None  # 내가 처음 도장 찍은 시각 (로그인 안 했으면 없음)
    visits: int = 0


class SeasonOut(BaseModel):
    season: int
    title: str
    radius_m: int
    points: int
    spots: list[SpotOut]
    visited: int


class VisitIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class VisitOut(BaseModel):
    place_id: int
    first: bool
    points: int
    visited: int
    total: int


@router.get("/challenge", response_model=SeasonOut)
def challenge(db: DbSession, reader: Reader):
    s = season()
    ids = [x["place_id"] for x in s["spots"]]
    places = {p.id: p for p in db.scalars(select(Place).where(Place.id.in_(ids)))} if ids else {}
    mine: dict[int, list[datetime]] = {}
    if reader.id:
        for pid, at in db.execute(
            select(ChallengeVisit.place_id, ChallengeVisit.visited_at)
            .where(ChallengeVisit.user_id == reader.id)
            .order_by(ChallengeVisit.visited_at)
        ):
            mine.setdefault(pid, []).append(at)
    spots = []
    for x in s["spots"]:
        p = places.get(x["place_id"])
        if p is None or not p.is_active:
            continue
        v = mine.get(p.id, [])
        spots.append(
            SpotOut(
                place_id=p.id,
                name=x["name"],
                region=x["region"],
                sea=x["sea"],
                lat=p.lat,
                lon=p.lon,
                info=SpotInfo(**x["info"]) if x.get("info") else None,
                visited_at=v[0] if v else None,
                visits=len(v),
            )
        )
    return SeasonOut(
        season=s["season"],
        title=s["title"],
        radius_m=s["radius_m"],
        points=s["points"],
        spots=spots,
        visited=sum(1 for sp in spots if sp.visited_at),
    )


def _is_night(p: Place, now: datetime) -> bool:
    k = now.astimezone(KST)
    rise, sset = sun_times(p.lat, p.lon, k.date())
    if not rise or not sset:
        return False
    hm = k.strftime("%H:%M")
    return hm < rise or hm > sset


@router.post("/challenge/{place_id}/visit", response_model=VisitOut)
def visit(place_id: int, body: VisitIn, user: CurrentUser, db: DbSession):
    s = season()
    if place_id not in {x["place_id"] for x in s["spots"]}:
        raise HTTPException(status_code=404, detail="탐험 장소가 아니에요")
    p = db.get(Place, place_id)
    if p is None or p.lat is None or p.lon is None:
        raise HTTPException(status_code=404, detail="장소 위치를 알 수 없어요")
    km = haversine_km(body.lat, body.lon, p.lat, p.lon)
    if km * 1000 > s["radius_m"]:
        dist = f"{km:.1f}km" if km >= 1 else f"{round(km * 1000)}m"
        raise HTTPException(
            status_code=409, detail=f"장소에서 {dist} 떨어져 있어요. {s['radius_m']}m 안에서 찍을 수 있어요"
        )
    now = utcnow()
    if warning.evaluate(db, p).level == "warning":
        raise HTTPException(
            status_code=409,
            detail="지금 이 바다에 해상 특보가 있어요. 안전을 위해 특보가 풀린 뒤 찍어 주세요",
        )
    if _is_night(p, now):
        raise HTTPException(
            status_code=409, detail="해가 진 뒤에는 도장을 찍을 수 없어요. 밝을 때 다시 와 주세요"
        )
    k = now.astimezone(KST)
    day_start = datetime(k.year, k.month, k.day, tzinfo=KST).astimezone(UTC)
    prev = db.scalars(
        select(ChallengeVisit).where(ChallengeVisit.user_id == user.id, ChallengeVisit.place_id == place_id)
    ).all()
    if any(v.visited_at >= day_start and v.visited_at < day_start + timedelta(days=1) for v in prev):
        raise HTTPException(status_code=409, detail="오늘은 이미 도장을 찍었어요")
    db.add(
        ChallengeVisit(
            user_id=user.id,
            place_id=place_id,
            season=s["season"],
            visited_at=now,
            within_m=100 if km <= 0.1 else 300,
        )
    )
    gained = recompute_points(db, user)
    db.commit()
    ids = {x["place_id"] for x in s["spots"]}
    visited = len(
        set(
            db.scalars(
                select(ChallengeVisit.place_id).where(
                    ChallengeVisit.user_id == user.id, ChallengeVisit.place_id.in_(ids)
                )
            ).all()
        )
    )
    return VisitOut(place_id=place_id, first=not prev, points=gained, visited=visited, total=len(ids))
