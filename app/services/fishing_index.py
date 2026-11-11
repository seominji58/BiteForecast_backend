"""어종별 공식 바다낚시지수 — 날짜 하나의 모든 지점을 한 번에 (홈 어종 탐색).

- 발표값을 그대로 전달한다. 등급이 없는 어종·시간대는 만들지 않는다
- 지점과 낚시터 연결: 지점 자체로 등록된 낚시터(official) / 지점에서 max_km 이내 일반 낚시터(참고)
- 위치 의심(D)·추천 보류 낚시터는 연결하지 않는다 (기존 정책)
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import FishingIndex, Place, PlaceStation, Station
from app.models.enums import StationRole
from app.schemas.fishing_index import FishingIndexDayOut, IndexPlaceLinkOut, IndexPointOut, IndexSpeciesOut
from app.services.compare import SPECIES_COMMON
from app.services.location import location_ctx

PERIOD_ORDER = {"오전": 0, "오후": 1, "일": 2}
OFFICIAL_KM = 0.05  # 지점 좌표와 같은 곳에 등록된 낚시터 = 공식 지점 자체
DISCLAIMER = (
    "국립해양조사원이 발표한 바다낚시지수예요. 「좋음」·「보통」 등은 기관 발표 등급이며 "
    "실제 조과나 출조 안전을 보장하지 않아요. 근처 낚시터의 지수는 가까운 지점의 참고값이에요."
)


def day_index(db: Session, day: date) -> FishingIndexDayOut:
    rows = db.scalars(select(FishingIndex).where(FishingIndex.day == day).order_by(FishingIndex.id)).all()
    max_km = get_settings().fishing_index_max_km
    by_station: dict[int, list[FishingIndex]] = defaultdict(list)
    for r in rows:
        by_station[r.station_id].append(r)
    ids = sorted(by_station)
    names = dict(db.execute(select(Station.id, Station.name).where(Station.id.in_(ids))).all()) if ids else {}

    loc = location_ctx(db)
    links: dict[int, list[IndexPlaceLinkOut]] = defaultdict(list)
    if ids:
        for ps in db.execute(
            select(PlaceStation.station_id, PlaceStation.place_id, PlaceStation.distance_km)
            .join(Place, Place.id == PlaceStation.place_id)
            .where(
                PlaceStation.role == StationRole.FISHING_INDEX,
                PlaceStation.station_id.in_(ids),
                Place.is_active.is_(True),
            )
            .order_by(PlaceStation.distance_km, PlaceStation.place_id)
        ):
            sid, pid, km = ps
            if pid in loc.suspects or pid in loc.holds:
                continue
            if km is None or km > max_km:
                continue
            links[sid].append(IndexPlaceLinkOut(place_id=pid, distance_km=km, official=km <= OFFICIAL_KM))

    points = []
    periods: set[str] = set()
    for sid in ids:
        grades: dict[str, dict[str, str]] = defaultdict(dict)
        tide: dict[str, str | None] = {}
        for r in by_station[sid]:
            periods.add(r.period)
            if r.index:
                name = SPECIES_COMMON if r.species == "-" else r.species
                grades[name][r.period] = r.index
            tide.setdefault(r.period, r.tide_phase)
            if r.tide_phase and not tide[r.period]:
                tide[r.period] = r.tide_phase
        points.append(
            IndexPointOut(
                station_id=sid,
                station_name=names.get(sid, ""),
                tide_phase=dict(sorted(tide.items(), key=lambda kv: PERIOD_ORDER.get(kv[0], 9))),
                species=[IndexSpeciesOut(species=k, grades=v) for k, v in grades.items()],
                places=links.get(sid, []),
            )
        )
    return FishingIndexDayOut(
        date=day,
        periods=sorted(periods, key=lambda p: PERIOD_ORDER.get(p, 9)),
        fetched_at=max((r.fetched_at for r in rows), default=None),
        max_km=max_km,
        points=points,
        disclaimer=DISCLAIMER,
    )
