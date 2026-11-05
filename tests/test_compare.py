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
        # 장소 A 에만 기상청 예보 격자 매핑. 내일 06시 파고 예보 1.0m
        grid = Station(provider="KMA", external_id="1,1", name="테스트 예보격자", kind=StationKind.KMA)
        db.add(grid)
        db.flush()
        db.add(PlaceStation(place_id=a.id, role=StationRole.FORECAST, station_id=grid.id, distance_km=2.0))
        db.add(
            OceanReading(
                station_id=grid.id,
                metric=Metric.WAVE_HEIGHT,
                kind=DataKind.FORECAST,
                t=lo + timedelta(days=1, hours=6),
                value=1.0,
                unit="m",
                issued_at=now,
                fetched_at=now,
            )
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
    # 오늘은 예보 자료가 없음(내일 것만 있음) → 실측 값이 예보 계열로 섞이지 않는다
    assert series(a, "wave_height", "forecast")["reason"] == "NO_DATA"


def test_future_date_uses_kma_forecast(client, setup):
    tomorrow = setup["today"] + timedelta(days=1)
    a, b = client.get(
        URL, params={"place_a": setup["a"], "place_b": setup["b"], "date": str(tomorrow)}
    ).json()["places"]
    fc = series(a, "wave_height", "forecast")
    assert fc["status"] == "ok" and [p["v"] for p in fc["points"]] == [1.0]
    assert fc["source"]["agency"] == "기상청" and fc["source"]["distance_km"] == 2.0
    assert series(a, "wave_height", "observed")["reason"] == "FUTURE_DATE"
    # 예보 격자가 매핑되지 않은 장소
    assert series(b, "wave_height", "forecast")["reason"] == "NO_STATION"


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


@pytest.fixture(scope="module")
def fishing_setup(client, setup):
    """장소 A: 지수 지점 3km (표시), 장소 B: 지수 지점 25km (TOO_FAR)"""
    from app.models import FishingIndex

    with SessionLocal() as db:
        near = Station(
            provider="KHOA", external_id="지수지점A", name="지수지점A", kind=StationKind.FISHING_INDEX
        )
        far = Station(
            provider="KHOA", external_id="지수지점B", name="지수지점B", kind=StationKind.FISHING_INDEX
        )
        db.add_all([near, far])
        db.flush()
        db.add_all(
            [
                PlaceStation(
                    place_id=setup["a"], role=StationRole.FISHING_INDEX, station_id=near.id, distance_km=3.0
                ),
                PlaceStation(
                    place_id=setup["b"], role=StationRole.FISHING_INDEX, station_id=far.id, distance_km=25.0
                ),
            ]
        )
        now = utcnow()
        for period, species, idx in [
            ("오후", "우럭", "보통"),
            ("오전", "감성돔", "좋음"),
            ("오전", "기타어종", "나쁨"),
        ]:
            for st in (near, far):
                db.add(
                    FishingIndex(
                        station_id=st.id,
                        day=setup["today"],
                        period=period,
                        species=species,
                        index=idx,
                        tide_phase="소조기",
                        fetched_at=now,
                    )
                )
        db.commit()
    return setup


def test_fishing_index_official_value_and_too_far(client, fishing_setup):
    s = fishing_setup
    a, b = client.get(URL, params={"place_a": s["a"], "place_b": s["b"], "date": str(s["today"])}).json()[
        "places"
    ]
    fa = a["fishing_index"]
    assert fa["status"] == "ok"
    assert fa["source"]["dataset"] == "바다낚시지수" and fa["source"]["distance_km"] == 3.0
    assert [p["period"] for p in fa["periods"]] == ["오전", "오후"]  # 시간대 순서
    assert [i["species"] for i in fa["periods"][0]["items"]] == ["감성돔", "기타어종"]  # 기타는 뒤로
    assert fa["periods"][0]["items"][0]["index"] == "좋음"  # 기관 발표값 그대로

    fb = b["fishing_index"]
    assert fb["status"] == "unavailable" and fb["reason"] == "TOO_FAR"
    assert fb["source"]["distance_km"] == 25.0 and fb["periods"] is None


def test_place_conditions(client, setup):
    r = client.get(f"/api/v1/places/{setup['a']}/conditions", params={"date": str(setup["today"])})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["place"]["place"]["name"] == "비교 A"
    assert any(s["metric"] == "tide_extreme" and s["status"] == "ok" for s in body["place"]["series"])
    assert (
        client.get("/api/v1/places/99999/conditions", params={"date": str(setup["today"])}).status_code == 400
    )


def test_fishing_index_refetches_when_new_station_mapped(client):
    """일부 지점만 받아둔 상태면 6시간 안이라도 다시 받는다 (새로 연결된 지점 누락 방지)"""
    from datetime import date

    from app.clients.khoa import FishingIndexRow
    from app.jobs.collect import _collect_fishing_index
    from app.models import FishingIndex

    today = today_kst()
    with SessionLocal() as db:
        old = Station(
            provider="KHOA", external_id="기존지점", name="기존지점", kind=StationKind.FISHING_INDEX
        )
        new = Station(provider="KHOA", external_id="새지점", name="새지점", kind=StationKind.FISHING_INDEX)
        db.add_all([old, new])
        db.flush()
        db.add(
            FishingIndex(
                station_id=old.id, day=today, period="오전", species="우럭", index="좋음", fetched_at=utcnow()
            )
        )
        db.commit()

        class FakeClient:
            calls = 0

            def fishing_index(self, day: date):
                FakeClient.calls += 1
                return [
                    FishingIndexRow(
                        p, today, "오전", "우럭", "보통", None, None, None, None, None, None, None
                    )
                    for p in ("기존지점", "새지점")
                ]

        from collections import Counter

        stats = Counter()
        _collect_fishing_index(db, FakeClient(), today, [old, new], stats)
        db.commit()
        assert FakeClient.calls == 1
        _collect_fishing_index(db, FakeClient(), today, [old, new], stats)  # 이제 모두 있음 → 건너뜀
        assert FakeClient.calls == 1 and stats["fishing_index_skipped"] == 1
