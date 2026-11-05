"""A/B 비교 API 테스트 (TC-01, TC-02, TC-03)"""

from datetime import timedelta

import pytest

from app.core.db import SessionLocal
from app.core.timeutil import kst_day_range, today_kst
from app.models import OceanReading, Place, PlaceStation, Region, Station, TideExtreme
from app.models.base import utcnow
from app.models.enums import DataKind, Metric, StationKind, StationRole, TideExtremeType

URL = "/api/v1/compare"


@pytest.fixture(scope="module")
def setup(client):
    """장소 A: 조석·부이 모두 매핑 / 장소 B: 조석만 매핑(부이 없음)"""
    today = today_kst()
    lo, _ = kst_day_range(today)
    now = utcnow()
    with SessionLocal() as db:
        region = Region(name="비교 테스트 해역")
        a, b = Place(name="비교 A", lat=37.0, lon=129.0), Place(name="비교 B", lat=37.1, lon=129.1)
        region.places = [a, b]
        tide = Station(provider="KHOA", external_id="DT_TEST", name="테스트 조위", kind=StationKind.TIDE)
        buoy = Station(provider="KHOA", external_id="TW_TEST", name="테스트 부이", kind=StationKind.BUOY)
        db.add_all([region, tide, buoy])
        db.flush()
        db.add_all(
            [
                PlaceStation(place_id=a.id, role=StationRole.TIDE, station_id=tide.id, distance_km=1.5),
                PlaceStation(place_id=a.id, role=StationRole.OCEAN, station_id=buoy.id, distance_km=None),
                PlaceStation(place_id=b.id, role=StationRole.TIDE, station_id=tide.id, distance_km=8.0),
                TideExtreme(
                    station_id=tide.id,
                    t=lo + timedelta(hours=6),
                    type=TideExtremeType.HIGH,
                    level_cm=500,
                    issued_at=now,
                    fetched_at=now,
                ),
                TideExtreme(
                    station_id=tide.id,
                    t=lo + timedelta(hours=12),
                    type=TideExtremeType.LOW,
                    level_cm=100,
                    issued_at=now,
                    fetched_at=now,
                ),
            ]
        )
        # 오늘 00시 실측: 파고 값 있음, 01시: 파고 결측(None), 02시: 파고 0.0 (실제 0)
        for h, v in [(0, 0.5), (1, None), (2, 0.0)]:
            db.add(
                OceanReading(
                    station_id=buoy.id,
                    metric=Metric.WAVE_HEIGHT,
                    kind=DataKind.OBSERVED,
                    t=lo + timedelta(hours=h),
                    value=v,
                    unit="m",
                    issued_at=lo + timedelta(hours=h),
                    fetched_at=now,
                )
            )
        db.commit()
        return {"a": a.id, "b": b.id, "today": today}


def series(place: dict, metric: str, kind: str) -> dict:
    return next(s for s in place["series"] if s["metric"] == metric and s["kind"] == kind)


def test_compare_today(client, setup):
    """TC-01: 두 장소 비교 결과와 자료 출처 표시"""
    res = client.get(URL, params={"place_a": setup["a"], "place_b": setup["b"], "date": str(setup["today"])})
    assert res.status_code == 200, res.text
    a, b = res.json()["places"]
    assert a["place"]["name"] == "비교 A" and b["place"]["name"] == "비교 B"

    ext = series(a, "tide_extreme", "forecast")
    assert ext["status"] == "ok"
    assert [e["type"] for e in ext["extremes"]] == ["high", "low"]
    assert ext["source"]["agency"] == "국립해양조사원" and ext["source"]["distance_km"] == 1.5

    wave = series(a, "wave_height", "observed")
    assert [p["v"] for p in wave["points"][:3]] == [0.5, None, 0.0]  # TC-02: 결측은 null, 0 은 0
    assert wave["source"]["distance_km"] is None  # 앱에서 「거리 확인 불가」

    # 부이가 없는 장소는 0 이 아니라 unavailable
    b_wave = series(b, "wave_height", "observed")
    assert b_wave["status"] == "unavailable" and b_wave["reason"] == "NO_STATION"
    assert b_wave["points"] is None
    # 규제 자료가 없으면 「확인되지 않음」
    assert a["regulation"]["status"] == "UNVERIFIED"


def test_forecast_and_observed_are_separate_series(client, setup):
    """TC-03: 실측과 예보를 한 계열에 섞지 않는다"""
    a = client.get(
        URL, params={"place_a": setup["a"], "place_b": setup["b"], "date": str(setup["today"])}
    ).json()["places"][0]
    kinds = [s["kind"] for s in a["series"] if s["metric"] == "wave_height"]
    assert sorted(kinds) == ["forecast", "observed"]
    assert series(a, "wave_height", "forecast")["reason"] == "NOT_CONNECTED"


def test_future_date_has_no_observed(client, setup):
    future = setup["today"] + timedelta(days=2)
    a = client.get(URL, params={"place_a": setup["a"], "place_b": setup["b"], "date": str(future)}).json()[
        "places"
    ][0]
    obs = series(a, "wave_height", "observed")
    assert obs["status"] == "unavailable" and obs["reason"] == "FUTURE_DATE"
    assert obs["points"] is None


def test_validation(client, setup):
    same = client.get(URL, params={"place_a": setup["a"], "place_b": setup["a"], "date": str(setup["today"])})
    assert same.status_code == 400
    far = setup["today"] + timedelta(days=60)
    assert (
        client.get(URL, params={"place_a": setup["a"], "place_b": setup["b"], "date": str(far)}).status_code
        == 400
    )
    assert (
        client.get(
            URL, params={"place_a": setup["a"], "place_b": 99999, "date": str(setup["today"])}
        ).status_code
        == 400
    )


def test_date_range(client):
    r = client.get("/api/v1/meta/date-range").json()
    assert r["min"] < r["today"] < r["max"]
