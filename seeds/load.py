"""지원 장소·관측소 시드 적재 (여러 번 실행해도 같은 결과).

- 관측소: seeds/stations.json (국립해양조사원 API 응답으로 확인한 목록), seeds/fishing_points.json
- 장소: seeds/places.json (scripts/build_places.py 로 생성)
- 장소마다 다음을 연결하고 거리를 저장한다 (FR-07)
  · tide: 가장 가까운 조석 예보지점 (MAX_KM 이내)
  · ocean: 파고·풍속을 관측하는 가장 가까운 부이 (MAX_KM 이내)
  · forecast: 기상청 단기예보 격자 — 부이가 있으면 부이 위치 격자(실측과 같은 지점), 없으면 장소 위치 격자
  · fishing_index: 가장 가까운 바다낚시지수 지점 (먼 경우 비교 화면에서 「가까운 지수 지점 없음」)
  거리가 기준을 넘으면 연결하지 않아 화면에 「가까운 관측소가 없습니다」로 표시된다.
- 시드에 없는 장소·지역과 개발용 샘플 해역은 비활성화한다

실행: python -m seeds.load
"""

import json
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal, init_db
from app.core.geo import haversine_km
from app.core.kma_grid import grid_to_latlon, latlon_to_grid
from app.models import Place, PlaceInfo, PlaceStation, Region, Station
from app.models.enums import PlaceType, StationKind, StationRole

HERE = Path(__file__).parent
PROVIDER = "KHOA"
MAX_KM = 30.0  # 관측소 연결 최대 거리


def _upsert_station(
    db, code: str, name: str, kind: StationKind, lat: float, lon: float, provider: str = PROVIDER
) -> Station:
    st = db.scalar(select(Station).where(Station.provider == provider, Station.external_id == code))
    if st is None:
        st = Station(provider=provider, external_id=code, kind=kind, name=name, lat=lat, lon=lon)
        db.add(st)
    else:
        st.name, st.kind, st.lat, st.lon = name, kind, lat, lon
    return st


def _map(db, place: Place, role: StationRole, st: Station | None, dist: float | None) -> None:
    ps = db.get(PlaceStation, (place.id, role))
    if st is None:
        if ps is not None:
            db.delete(ps)
        return
    if ps is None:
        ps = PlaceStation(place_id=place.id, role=role)
        db.add(ps)
    ps.station_id, ps.distance_km = st.id, round(dist, 1) if dist is not None else None


def _nearest(place: Place, candidates: list[Station], max_km: float | None = MAX_KM):
    st, d = min(
        ((s, haversine_km(place.lat, place.lon, s.lat, s.lon)) for s in candidates), key=lambda x: x[1]
    )
    return (st, d) if max_km is None or d <= max_km else (None, d)


def _grid_station(db, nx: int, ny: int, name: str) -> Station:
    lat, lon = grid_to_latlon(nx, ny)
    return _upsert_station(db, f"{nx},{ny}", name, StationKind.KMA, lat, lon, provider="KMA")


def main() -> None:
    init_db()
    stations = json.loads((HERE / "stations.json").read_text(encoding="utf-8"))
    places = json.loads((HERE / "places.json").read_text(encoding="utf-8"))
    fishing_points = json.loads((HERE / "fishing_points.json").read_text(encoding="utf-8"))["points"]

    with SessionLocal() as db:
        tides = [
            _upsert_station(db, s["code"], s["name"], StationKind.TIDE, s["lat"], s["lon"])
            for s in stations["tide"]
        ]
        # 비교 화면의 핵심 지표(파고·풍속)를 모두 관측하는 부이만 매핑 후보로 쓴다
        buoys = [
            _upsert_station(db, s["code"], s["name"], StationKind.BUOY, s["lat"], s["lon"])
            for s in stations["buoy"]
            if s.get("has_wave") and s.get("has_wind")
        ]
        for s in stations["buoy"]:
            if not (s.get("has_wave") and s.get("has_wind")):
                _upsert_station(db, s["code"], s["name"], StationKind.BUOY, s["lat"], s["lon"])
        fishing = [
            _upsert_station(db, f["name"], f["name"], StationKind.FISHING_INDEX, f["lat"], f["lon"])
            for f in fishing_points
        ]
        db.flush()

        active_place_ids: set[int] = set()
        active_region_ids: set[int] = set()
        stats = {"places": 0, "tide": 0, "ocean": 0, "index_near": 0}

        for reg in places["regions"]:
            region = db.scalar(select(Region).where(Region.name == reg["name"]))
            if region is None:
                region = Region(name=reg["name"])
                db.add(region)
                db.flush()
            region.is_active = True
            active_region_ids.add(region.id)

            for p in reg["places"]:
                place = db.scalar(select(Place).where(Place.region_id == region.id, Place.name == p["name"]))
                if place is None:
                    place = Place(region_id=region.id, name=p["name"])
                    db.add(place)
                place.type, place.lat, place.lon, place.is_active = (
                    PlaceType(p["type"]),
                    p["lat"],
                    p["lon"],
                    True,
                )
                db.flush()
                active_place_ids.add(place.id)

                info = p.get("info") or {}
                pi = db.get(PlaceInfo, place.id) or PlaceInfo(place_id=place.id)
                for k in ("source", "address", "phone", "species", "fee", "facility", "manager", "data_date"):
                    setattr(pi, k, info.get(k) if k != "source" else info.get(k, "알 수 없음"))
                db.add(pi)

                tide_st, tide_d = _nearest(place, tides)
                _map(db, place, StationRole.TIDE, tide_st, tide_d)
                buoy_st, buoy_d = _nearest(place, buoys)
                _map(db, place, StationRole.OCEAN, buoy_st, buoy_d)

                if buoy_st is not None:
                    nx, ny = latlon_to_grid(buoy_st.lat, buoy_st.lon)
                    grid = _grid_station(db, nx, ny, f"{buoy_st.name} 부근 예보격자")
                    grid_d = buoy_d
                else:
                    nx, ny = latlon_to_grid(place.lat, place.lon)
                    grid = _grid_station(db, nx, ny, f"{place.name} 부근 예보격자")
                    glat, glon = grid_to_latlon(nx, ny)
                    grid_d = haversine_km(place.lat, place.lon, glat, glon)
                db.flush()
                _map(db, place, StationRole.FORECAST, grid, grid_d)

                fish_st, fish_d = _nearest(place, fishing, max_km=None)
                _map(db, place, StationRole.FISHING_INDEX, fish_st, fish_d)

                stats["places"] += 1
                stats["tide"] += tide_st is not None
                stats["ocean"] += buoy_st is not None
                stats["index_near"] += fish_d <= 10

        # 시드에 없는 장소·지역(개발용 샘플 포함)은 비활성화
        for r in db.scalars(select(Region)):
            if r.id not in active_region_ids:
                r.is_active = False
        for p in db.scalars(select(Place)):
            if p.id not in active_place_ids:
                p.is_active = False

        db.commit()
        n = stats["places"]
        print(
            f"장소 {n}곳 적재 · 조석 지점 연결 {stats['tide']}/{n} · 부이 연결 {stats['ocean']}/{n} · "
            f"바다낚시지수 10km 이내 {stats['index_near']}/{n} (연결 기준 {MAX_KM:.0f}km)"
        )


if __name__ == "__main__":
    main()
