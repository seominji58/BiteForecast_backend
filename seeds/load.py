"""실제 지원 해역·장소·관측소 시드 적재 (여러 번 실행해도 같은 결과).

- 관측소: seeds/stations.json (국립해양조사원 API 응답으로 확인한 목록)
- 장소: seeds/places.json
- 장소마다 가장 가까운 조석 예보지점(tide)과, 파고·풍속을 관측하는 가장 가까운 부이(ocean)를 매핑하고
  거리를 계산해 저장한다 (FR-07)
- 개발용 샘플 해역(seeds/dev_sample.py)은 비활성화한다

실행: python -m seeds.load
"""

import json
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal, init_db
from app.core.geo import haversine_km
from app.models import Place, PlaceStation, Region, Station
from app.models.enums import PlaceType, StationKind, StationRole

HERE = Path(__file__).parent
PROVIDER = "KHOA"


def _upsert_station(db, code: str, name: str, kind: StationKind, lat: float, lon: float) -> Station:
    st = db.scalar(select(Station).where(Station.provider == PROVIDER, Station.external_id == code))
    if st is None:
        st = Station(provider=PROVIDER, external_id=code, kind=kind, name=name, lat=lat, lon=lon)
        db.add(st)
    else:
        st.name, st.kind, st.lat, st.lon = name, kind, lat, lon
    return st


def _nearest(place: Place, candidates: list[tuple[Station, dict]]) -> tuple[Station, float]:
    return min(
        ((st, haversine_km(place.lat, place.lon, st.lat, st.lon)) for st, _ in candidates),
        key=lambda x: x[1],
    )


def main() -> None:
    init_db()
    stations = json.loads((HERE / "stations.json").read_text(encoding="utf-8"))
    places = json.loads((HERE / "places.json").read_text(encoding="utf-8"))

    with SessionLocal() as db:
        tides = [
            (_upsert_station(db, s["code"], s["name"], StationKind.TIDE, s["lat"], s["lon"]), s)
            for s in stations["tide"]
        ]
        buoys = [
            (_upsert_station(db, s["code"], s["name"], StationKind.BUOY, s["lat"], s["lon"]), s)
            for s in stations["buoy"]
        ]
        # 비교 화면의 핵심 지표(파고·풍속)를 모두 관측하는 부이만 매핑 후보로 쓴다
        ocean_candidates = [(st, s) for st, s in buoys if s.get("has_wave") and s.get("has_wind")]
        db.flush()

        # 개발용 샘플 해역 비활성화
        for r in db.scalars(select(Region).where(Region.name.like("샘플 해역%"))):
            r.is_active = False
            for p in r.places:
                p.is_active = False

        n_places = 0
        for reg in places["regions"]:
            region = db.scalar(select(Region).where(Region.name == reg["name"]))
            if region is None:
                region = Region(name=reg["name"])
                db.add(region)
                db.flush()
            region.is_active = True

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

                for role, cands in ((StationRole.TIDE, tides), (StationRole.OCEAN, ocean_candidates)):
                    st, dist = _nearest(place, cands)
                    ps = db.get(PlaceStation, (place.id, role))
                    if ps is None:
                        ps = PlaceStation(place_id=place.id, role=role)
                        db.add(ps)
                    ps.station_id, ps.distance_km = st.id, round(dist, 1)
                    label = f"{reg['name']} {p['name']:<6} {role.value:<5}"
                    print(f"  {label} → {st.external_id} {st.name} ({dist:.1f}km)")
                n_places += 1

        db.commit()
        print(f"관측소 {len(tides) + len(buoys)}곳, 장소 {n_places}곳 적재 완료")


if __name__ == "__main__":
    main()
