"""풍향 (기상청 단기예보 VEC) — 16방위 변환, 가장 센 바람 시각의 풍향"""

from datetime import timedelta

from app.core.timeutil import today_kst
from app.services.summary import deg_to_dir16


def test_deg_to_dir16():
    assert deg_to_dir16(0) == "북" and deg_to_dir16(359) == "북"
    assert deg_to_dir16(45) == "북동" and deg_to_dir16(315) == "북서"
    assert deg_to_dir16(180) == "남" and deg_to_dir16(247.5) == "서남서"


def test_summary_wind_dir_at_peak(client):
    from app.core.db import SessionLocal
    from app.core.timeutil import kst_day_range
    from app.models import OceanReading, Place, PlaceStation, Region, Station
    from app.models.base import utcnow
    from app.models.enums import DataKind, Metric, StationKind, StationRole
    from app.services import summary as summary_service

    day = today_kst() + timedelta(days=1)
    lo, _ = kst_day_range(day)
    now = utcnow()
    with SessionLocal() as db:
        r = Region(name="충남 풍향시험군")
        p = Place(name="풍향-테스트", lat=36.3, lon=126.5)
        r.places = [p]
        grid = Station(provider="KMA", external_id="8,8", name="풍향 격자", kind=StationKind.KMA)
        db.add_all([r, grid])
        db.flush()
        db.add(PlaceStation(place_id=p.id, role=StationRole.FORECAST, station_id=grid.id, distance_km=1.0))
        for h in range(24):
            t = lo + timedelta(hours=h)
            for metric, unit, v in (
                (Metric.WIND_SPEED, "m/s", 9.0 if h == 14 else 3.0),
                (Metric.WIND_DIRECTION, "deg", 315.0 if h == 14 else 90.0),
            ):
                db.add(OceanReading(station_id=grid.id, metric=metric, kind=DataKind.FORECAST, t=t, value=v,
                                    unit=unit, issued_at=now, fetched_at=now))
        db.commit()
        pid = p.id
    summary_service._cache.clear()
    rows = client.get(f"/api/v1/places-summary?date={day}").json()["places"]
    s = next(x for x in rows if x["place_id"] == pid)
    assert s["wind_fc_max"]["v"] == 9.0
    assert s["wind_dir_fc"] == "북서"  # 가장 센 바람(14시)의 풍향, 평소 동풍이 아니라
