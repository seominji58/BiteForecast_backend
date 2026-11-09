"""좌표 의심 낚시터 · 다른 바다 조위관측소 (2026-11-09 데이터 연결 검증)"""

from datetime import timedelta

from app.core.db import SessionLocal
from app.core.timeutil import kst_day_range, today_kst
from app.models import Place, PlaceStation, Region, Station, TideExtreme
from app.models.base import utcnow
from app.models.enums import StationKind, StationRole, TideExtremeType


def test_suspect_place_gets_no_data_and_different_sea_tide_is_hidden(client):
    lo, _ = kst_day_range(today_kst())
    now = utcnow()
    with SessionLocal() as db:
        # 강원 고성군(동해) 3곳 정상 + 1곳은 서해 좌표로 잘못 등록
        east = Region(name="강원 위치검사군")
        ok = [Place(name=f"동해 정상{i}", lat=38.30 + i * 0.01, lon=128.55) for i in range(3)]
        bad = Place(name="동해 좌표오류", lat=37.0, lon=126.2)
        east.places = [*ok, bad]
        # 충남(서해) 낚시터 — 서해 관측소의 「가장 가까운 낚시터」가 되도록 관측소 바로 옆
        west = Region(name="충남 위치검사군")
        wp = Place(name="서해 기준", lat=36.90, lon=125.50)
        west.places = [wp]
        tide = Station(
            provider="KHOA",
            external_id="DT_LOC",
            name="서해 테스트 조위",
            kind=StationKind.TIDE,
            lat=36.90,
            lon=125.51,
        )
        db.add_all([east, west, tide])
        db.flush()
        db.add_all(
            [
                PlaceStation(place_id=ok[0].id, role=StationRole.TIDE, station_id=tide.id, distance_km=25.0),
                TideExtreme(
                    station_id=tide.id,
                    t=lo + timedelta(hours=6),
                    type=TideExtremeType.HIGH,
                    level_cm=500,
                    issued_at=now,
                    fetched_at=now,
                ),
            ]
        )
        db.commit()
        ok_id, bad_id = ok[0].id, bad.id

    day = str(today_kst())
    b = client.get(f"/api/v1/places/{bad_id}/conditions", params={"date": day}).json()["place"]
    assert b["place"]["location_suspect"] is True
    assert b["warning"]["reason"] == "LOCATION_CHECK"
    assert all(s["status"] == "unavailable" and s["reason"] == "LOCATION_CHECK" for s in b["series"])
    assert client.get(f"/api/v1/places/{bad_id}").json()["location_suspect"] is True

    o = client.get(f"/api/v1/places/{ok_id}/conditions", params={"date": day}).json()["place"]
    assert o["place"]["location_suspect"] is False
    tide_s = [s for s in o["series"] if s["metric"] in ("tide_extreme", "tide_level")]
    assert tide_s and all(s["reason"] == "DIFFERENT_SEA" for s in tide_s)

    from app.services import summary as summary_service

    summary_service._cache.clear()  # 앞 테스트의 10분 캐시
    summary = {p["place_id"]: p for p in client.get(f"/api/v1/places-summary?date={day}").json()["places"]}
    assert summary[bad_id]["location_suspect"] is True
    assert summary[ok_id]["sea_group"] == "동해" and summary[ok_id]["next_tide"] is None
