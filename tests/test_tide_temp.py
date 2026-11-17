"""조위관측소 실측 수온 — 부이 수온이 없을 때만 대신 쓰고, 출처를 조위관측소로 밝힌다"""

import uuid
from datetime import timedelta

from app.core.timeutil import today_kst


def _setup(with_buoy: bool):
    from app.core.db import SessionLocal
    from app.core.timeutil import kst_day_range
    from app.models import OceanReading, Place, PlaceStation, Region, Station
    from app.models.base import utcnow
    from app.models.enums import DataKind, Metric, StationKind, StationRole

    day = today_kst()
    lo, _ = kst_day_range(day)
    now = utcnow()
    with SessionLocal() as db:
        r = Region(name=f"충남 수온시험{'부이' if with_buoy else ''}")
        p = Place(name="수온-테스트", lat=36.3, lon=126.5)
        r.places = [p]
        tide = Station(provider="KHOA", external_id=f"DT_{uuid.uuid4().hex[:8]}", name="시험 조위관측소", kind=StationKind.TIDE)
        db.add_all([r, tide])
        db.flush()
        db.add(PlaceStation(place_id=p.id, role=StationRole.TIDE, station_id=tide.id, distance_km=5.0))
        db.add(OceanReading(station_id=tide.id, metric=Metric.WATER_TEMP, kind=DataKind.OBSERVED, t=lo,
                            value=14.8, unit="°C", issued_at=lo, fetched_at=now))
        if with_buoy:
            buoy = Station(provider="KHOA", external_id=f"TW_{uuid.uuid4().hex[:8]}", name="시험 부이", kind=StationKind.BUOY)
            db.add(buoy)
            db.flush()
            db.add(PlaceStation(place_id=p.id, role=StationRole.OCEAN, station_id=buoy.id, distance_km=10.0))
            db.add(OceanReading(station_id=buoy.id, metric=Metric.WATER_TEMP, kind=DataKind.OBSERVED, t=lo,
                                value=16.2, unit="°C", issued_at=lo, fetched_at=now))
        db.commit()
        return p.id, day


def _temp_series(client, pid, day):
    pc = client.get(f"/api/v1/places/{pid}/conditions", params={"date": str(day)}).json()["place"]
    return next(s for s in pc["series"] if s["metric"] == "water_temp" and s["kind"] == "observed")


def test_tide_station_temp_when_no_buoy(client):
    pid, day = _setup(with_buoy=False)
    s = _temp_series(client, pid, day)
    assert s["status"] == "ok" and s["points"][0]["v"] == 14.8
    assert s["source"]["dataset"] == "조위관측소 실측 수온" and s["source"]["station_name"] == "시험 조위관측소"


def test_buoy_temp_preferred(client):
    pid, day = _setup(with_buoy=True)
    s = _temp_series(client, pid, day)
    assert s["points"][0]["v"] == 16.2 and s["source"]["dataset"] == "해양관측부이 최신 관측데이터"


def test_no_temp_for_future_date(client):
    pid, _ = _setup(with_buoy=False)
    s = _temp_series(client, pid, today_kst() + timedelta(days=1))
    assert s["status"] == "unavailable"
