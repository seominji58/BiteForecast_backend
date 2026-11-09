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

from app.models import Place, PlaceCoordCheck, Station
from app.schemas.place import CoordOut, PlaceOut
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
    """정밀 위치 기반 기능에서 뺄 낚시터 ID = 자동 규칙 ∪ 수동 목록 ∪ 최근 검증 기록이 D 등급인 곳.

    원본 데이터·일반 상세 정보는 그대로 두고, 해황 연결·지도·거리순·추천에서만 뺀다.
    """
    version = db.execute(select(func.count(Place.id), func.max(Place.id))).one()
    graded_d = frozenset(pid for pid, c in coord_states(db).items() if c.grade == "D")
    return _suspects_cached((int(version[0]), int(version[1] or 0))) | MANUAL_CHECK_IDS | graded_d


def review_hold_ids(db: Session) -> frozenset[int]:
    """좌표 불일치 의심(추가 검증 필요) 낚시터 — C등급 유지, 추천·좌표 기준 해황 판단 보류"""
    return frozenset(pid for pid, c in coord_states(db).items() if c.recommend_hold)


# --- 좌표 검증 기록 (place_coord_check) ---

_LABEL = {
    "fishing_spot": "실제 낚시 위치 확인",
    "harbor": "항구·해변 대표 위치",
    "business_address": "대략 위치 · 사업장·어촌계 대표 주소 기준",
    "approx_area": "대략 위치 · 반올림·공유 좌표",
    "agency_point": "기관 지정 대표 지점",
    "unverifiable": "위치 확인 필요",
    "unknown": "신고 좌표 · 실제 낚시 지점 미확인",
}


def _coord_out(c: PlaceCoordCheck) -> CoordOut:
    approx = c.sub_grade == "C2" or c.location_type in ("business_address", "approx_area")
    label = _LABEL.get(c.location_type, _LABEL["unknown"])
    hold = c.status == "coord_mismatch_suspected"
    if c.grade == "D":
        label = _LABEL["unverifiable"]
    elif hold:
        # 주소와 좌표의 행정구역이 다름 — 위치를 정밀하게 쓰지 않는다
        label, approx = "좌표 불일치 의심 · 추가 검증 필요", True
    elif c.status == "address_location_candidate":
        label = "사업장 주소 위치 · 실제 낚시 지점 미확인"
    elif c.grade == "C" and c.location_type == "harbor":
        label = "항구·해변 대표 위치(추정)"
    return CoordOut(
        grade=c.grade,  # type: ignore[arg-type]
        sub_grade=c.sub_grade,
        location_type=c.location_type,
        status=c.status,
        approx=approx,
        label=label,
        recommend_hold=hold,
        checked_at=c.checked_at,
    )


@lru_cache(maxsize=4)
def _coord_cached(version: tuple[int, int]) -> dict[int, CoordOut]:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        # 장소마다 가장 최근 기록 (같은 시각이면 나중에 넣은 것)
        latest = (
            select(PlaceCoordCheck.place_id, func.max(PlaceCoordCheck.id).label("mid"))
            .group_by(PlaceCoordCheck.place_id)
            .subquery()
        )
        rows = db.scalars(select(PlaceCoordCheck).join(latest, PlaceCoordCheck.id == latest.c.mid)).all()
        return {r.place_id: _coord_out(r) for r in rows}


def coord_states(db: Session) -> dict[int, CoordOut]:
    """장소별 현재 좌표 품질 (가장 최근 검증 기록). 기록이 바뀌면 다시 읽는다"""
    v = db.execute(select(func.count(PlaceCoordCheck.id), func.max(PlaceCoordCheck.id))).one()
    return _coord_cached((int(v[0]), int(v[1] or 0)))


def place_out(db: Session, place: Place) -> PlaceOut:
    """응답용 낚시터 (위치 확인 필요 여부·좌표 품질 포함)"""
    return PlaceOut.model_validate(place).model_copy(
        update={
            "location_suspect": place.id in suspect_place_ids(db),
            "coord": coord_states(db).get(place.id),
        }
    )


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
