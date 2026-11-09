"""낚시터 위치·자료 대표성 점검 (2026-11-09 데이터 연결 검증 결과 반영).

1) 좌표 의심: 공공데이터 원본 좌표가 같은 시·도의 다른 낚시터들과 크게 어긋나면(예: 충남 서산시 낚시터 6곳이
   부산 좌표로 등록됨) 「위치 확인 필요」로 보고 해황 자료를 연결하지 않는다. DB 좌표는 바꾸지 않는다.
2) 조위관측소 대표성: 거리만으로 확정하지 않는다. 낚시터와 관측소가 「같은 바다」를 볼 때만 참고 자료로 쓰고,
   다른 바다면 연결하지 않는다. 관측소가 보는 바다는 그 관측소에서 가장 가까운
   (좌표 정상) 낚시터의 바다로 추정.
"""

import math
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Place, Station
from app.services.warning import sea_keywords

# 같은 시·도의 (좌표가 다른) 가장 가까운 낚시터가 이만큼 넘게 떨어져 있고,
# 다른 시·도 낚시터가 그보다 훨씬(1/3 이하) 가까우면 좌표 의심.
# 같은 시·군 중앙값으로 보면 서산 7곳 중 6곳이 같은 잘못된 좌표라 중앙값 자체가 부산으로 가고,
# 가거도·먼바다 포인트처럼 원래 먼 곳을 잘못 잡는다 → 시·도 단위 이웃 비교로 판단.
SUSPECT_KM = 60.0

# 규칙으로 못 잡는(같은 시·도 안에서 틀린) 좌표를 사람이 확인해 넣는 목록. DB 좌표는 그대로 둔다.
# 176 창리해상낚시터: 주소는 서산시 부석면 창리 지선인데 원본 좌표가 보령 앞바다
#   (2026-11-09 보고서 docs/03_데이터/2026-11-09_서산_낚시터_좌표_보정_후보.md, 사용자 승인)
MANUAL_CHECK_IDS: frozenset[int] = frozenset({176})


def _km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = math.pi / 180
    h = (
        math.sin((b_lat - a_lat) * r / 2) ** 2
        + math.cos(a_lat * r) * math.cos(b_lat * r) * math.sin((b_lon - a_lon) * r / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


@lru_cache(maxsize=4)
def _suspects_cached(version: tuple[int, int]) -> frozenset[int]:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        places = [
            (p.id, p.region.name.split()[0], p.lat, p.lon)
            for p in db.scalars(
                select(Place).where(Place.is_active.is_(True)).options(selectinload(Place.region))
            ).all()
            if p.lat is not None and p.lon is not None
        ]
    out = set()
    for pid, sido, lat, lon in places:
        same = [
            _km(lat, lon, b[2], b[3])
            for b in places
            if b[0] != pid and b[1] == sido and (b[2], b[3]) != (lat, lon)
        ]
        other = [_km(lat, lon, b[2], b[3]) for b in places if b[1] != sido]
        if not same or not other:
            continue  # 비교할 이웃이 없으면 판단하지 않는다
        if min(same) > SUSPECT_KM and min(other) * 3 < min(same):
            out.add(pid)
    return frozenset(out)


def suspect_place_ids(db: Session) -> frozenset[int]:
    """좌표가 의심되는 낚시터 ID (낚시터 목록이 바뀌면 다시 계산)"""
    version = db.execute(select(func.count(Place.id), func.max(Place.id))).one()
    return _suspects_cached((int(version[0]), int(version[1] or 0))) | MANUAL_CHECK_IDS


@lru_cache(maxsize=4)
def _station_seas_cached(version: tuple[int, int, int]) -> dict[int, frozenset[str]]:
    from app.core.db import SessionLocal

    suspects = _suspects_cached(version[:2]) | MANUAL_CHECK_IDS
    with SessionLocal() as db:
        places = [
            p
            for p in db.scalars(
                select(Place).where(Place.is_active.is_(True)).options(selectinload(Place.region))
            ).all()
            if p.lat is not None and p.id not in suspects
        ]
        stations = db.scalars(select(Station).where(Station.lat.is_not(None))).all()
    seas: dict[int, frozenset[str]] = {}
    for st in stations:
        nearest = min(places, key=lambda p: _km(st.lat, st.lon, p.lat, p.lon), default=None)
        seas[st.id] = frozenset(sea_keywords(nearest)[0]) if nearest else frozenset()
    return seas


def same_sea(db: Session, place: Place, station_id: int) -> bool | None:
    """낚시터와 관측소가 같은 바다를 보는지. 판단할 수 없으면 None"""
    pv = db.execute(select(func.count(Place.id), func.max(Place.id))).one()
    sv = db.scalar(select(func.count(Station.id))) or 0
    seas = _station_seas_cached((int(pv[0]), int(pv[1] or 0), int(sv)))
    st_sea = seas.get(station_id)
    p_sea = set(sea_keywords(place)[0])
    if not st_sea or not p_sea:
        return None
    return bool(st_sea & p_sea)
