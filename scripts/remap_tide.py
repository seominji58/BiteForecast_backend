"""물때(조석 예보지점) 연결이 없는 장소에 60km 안의 가장 가까운 지점을 연결한다 (2026-11-23).

조석 예보지점이 전국 42곳뿐이라 30km 기준으로는 섬·외곽 29곳이 물때 빈칸이었다.
30km를 넘는 연결은 앱에서 「참고 · 목포 43km 기준」처럼 거리를 붙여 보여준다.
같은 바다인지 검사(compare.same_sea)는 화면에 낼 때 그대로 적용된다 — 다른 바다면 여전히 표시하지 않는다.
이미 연결된 곳·비활성 장소·좌표 없는 곳은 건드리지 않는다. 여러 번 실행해도 같은 결과.

실행: python scripts/remap_tide.py          (미리 보기)
      python scripts/remap_tide.py --apply  (DB에 쓰기)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.geo import haversine_km  # noqa: E402
from app.models import Place, PlaceStation, Station  # noqa: E402
from app.models.enums import StationKind, StationRole  # noqa: E402

TIDE_MAX_KM = 60.0


def main(apply: bool) -> None:
    db = SessionLocal()
    tides = db.scalars(select(Station).where(Station.kind == StationKind.TIDE)).all()
    mapped = set(db.scalars(select(PlaceStation.place_id).where(PlaceStation.role == StationRole.TIDE)).all())
    places = db.scalars(select(Place).where(Place.is_active.is_(True))).all()
    added = []
    for p in places:
        if p.id in mapped or p.lat is None or p.lon is None:
            continue
        st, d = min(((s, haversine_km(p.lat, p.lon, s.lat, s.lon)) for s in tides), key=lambda x: x[1])
        if d > TIDE_MAX_KM:
            print(f"  건너뜀 {p.name}: 가장 가까운 {st.name} {d:.0f}km")
            continue
        added.append((p.name, st.name, round(d, 1)))
        if apply:
            db.add(PlaceStation(place_id=p.id, role=StationRole.TIDE, station_id=st.id, distance_km=round(d, 1)))
    for a in added:
        print("  연결", *a)
    print(f"{'적용' if apply else '미리 보기'}: {len(added)}곳 연결 (조석 지점 {len(tides)}곳, 기준 {TIDE_MAX_KM:.0f}km)")
    if apply:
        db.commit()
    db.close()


if __name__ == "__main__":
    main("--apply" in sys.argv)
