"""출조계획 API (설계안 docs/05_UX/2026-11-09_출조계획_설계안.md)"""

from datetime import timedelta

from app.core.timeutil import today_kst
from tests.conftest import signup

URL = "/api/v1/me/trips"


def _d(n: int) -> str:
    return str(today_kst() + timedelta(days=n))


def test_login_required(client):
    assert client.get(URL).status_code == 401
    assert client.post(URL, json={"start_date": _d(1), "end_date": _d(1)}).status_code == 401


def test_create_get_update_delete(client, places, device):
    body = {
        "start_date": _d(5),
        "end_date": _d(6),
        "region": "제주",
        "stops": [
            {"day": _d(5), "place_id": places[0], "start_time": "06:00", "end_time": "10:00"},
            {"day": _d(5), "place_id": places[1], "role": "alternative"},
            {"day": _d(6), "place_id": places[2]},
        ],
    }
    r = client.post(URL, json=body, headers=device)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["title"].endswith("제주 출조")  # 제목 자동
    assert [s["sort_order"] for s in t["stops"]] == [0, 1, 0]
    assert len(t["checklist"]) == 4  # 기본 준비물
    tid = t["id"]

    lst = client.get(URL, headers=device).json()
    item = next(x for x in lst if x["id"] == tid)
    assert item["stop_count"] == 3 and item["checklist_total"] == 4
    assert all(x["id"] != tid for x in client.get(URL + "?when=past", headers=device).json())

    # 기간을 줄여 장소가 밖으로 나가면 거절
    r = client.patch(f"{URL}/{tid}", json={"end_date": _d(5)}, headers=device)
    assert r.status_code == 400 and "기간 밖" in r.json()["error"]["message"]
    r = client.patch(f"{URL}/{tid}", json={"title": "제주 주말", "memo": "새벽 출발"}, headers=device)
    assert r.json()["title"] == "제주 주말" and r.json()["memo"] == "새벽 출발"

    # 장소 추가·수정·삭제
    r = client.post(f"{URL}/{tid}/stops", json={"day": _d(6), "place_id": places[0]}, headers=device)
    assert r.status_code == 201 and len(r.json()["stops"]) == 4
    sid = r.json()["stops"][-1]["id"]
    r = client.patch(
        f"{URL}/{tid}/stops/{sid}", json={"memo": "물때 확인", "role": "alternative"}, headers=device
    )
    s = next(x for x in r.json()["stops"] if x["id"] == sid)
    assert s["memo"] == "물때 확인" and s["role"] == "alternative"
    r = client.delete(f"{URL}/{tid}/stops/{sid}", headers=device)
    assert len(r.json()["stops"]) == 3

    # 준비물 통째로 저장
    r = client.put(
        f"{URL}/{tid}/checklist",
        json=[{"label": "낚싯대", "checked": True}, {"label": "얼음"}],
        headers=device,
    )
    assert [(c["label"], c["checked"]) for c in r.json()["checklist"]] == [("낚싯대", True), ("얼음", False)]

    assert client.delete(f"{URL}/{tid}", headers=device).status_code == 204
    assert client.get(f"{URL}/{tid}", headers=device).status_code == 404


def test_validation(client, places, device):
    def post(**kw):
        return client.post(URL, json={"start_date": _d(1), "end_date": _d(1), **kw}, headers=device)

    assert post(end_date=_d(0)).status_code == 400  # 끝 < 시작
    assert post(end_date=_d(8)).status_code == 400  # 8일 > 7일
    assert post(start_date=_d(400), end_date=_d(400)).status_code == 400  # 1년 넘게 앞
    assert post(start_date=_d(-40), end_date=_d(-40)).status_code == 400
    assert post(stops=[{"day": _d(2), "place_id": places[0]}]).status_code == 400  # 기간 밖 장소
    assert post(stops=[{"day": _d(1), "place_id": 999999}]).status_code == 400
    assert post(stops=[{"day": _d(1), "place_id": places[0]}] * 6).status_code == 400  # 하루 5곳 초과
    # 예보 범위 밖 먼 미래도 저장할 수 있다
    assert post(start_date=_d(200), end_date=_d(201)).status_code == 201


def test_only_owner(client, places, device):
    tid = client.post(URL, json={"start_date": _d(1), "end_date": _d(1)}, headers=device).json()["id"]
    other = signup(client)
    assert client.get(f"{URL}/{tid}", headers=other).status_code == 404
    assert client.patch(f"{URL}/{tid}", json={"title": "x"}, headers=other).status_code == 404
    assert client.delete(f"{URL}/{tid}", headers=other).status_code == 404
    assert client.get(f"{URL}/{tid}/outlook", headers=other).status_code == 404
    assert all(x["id"] != tid for x in client.get(URL, headers=other).json())


def test_outlook_statuses(client, places, device):
    # 어제(지난 날짜) 계획 하나 + 먼 미래 계획 하나
    past = client.post(
        URL,
        json={"start_date": _d(-1), "end_date": _d(-1), "stops": [{"day": _d(-1), "place_id": places[0]}]},
        headers=device,
    ).json()
    far = client.post(
        URL,
        json={"start_date": _d(100), "end_date": _d(100), "stops": [{"day": _d(100), "place_id": places[0]}]},
        headers=device,
    ).json()
    o = client.get(f"{URL}/{past['id']}/outlook", headers=device).json()
    assert o["stops"][0]["forecast_status"] == "past"
    o = client.get(f"{URL}/{far['id']}/outlook", headers=device).json()
    s = o["stops"][0]
    # 예보 발표 전: 값을 만들지 않는다
    assert s["forecast_status"] == "pending" and s["wave_fc_max"] is None and s["wind_fc_max"] is None
    # 지난 계획은 past 목록에
    assert any(x["id"] == past["id"] for x in client.get(URL + "?when=past", headers=device).json())


def test_journal_link(client, places, device):
    t = client.post(
        URL,
        json={"start_date": _d(-1), "end_date": _d(-1), "stops": [{"day": _d(-1), "place_id": places[0]}]},
        headers=device,
    ).json()
    sid = t["stops"][0]["id"]
    fished = f"{_d(-1)}T07:00:00+09:00"
    # 다른 낚시터로는 연결 불가
    r = client.post(
        "/api/v1/journals",
        json={"place_id": places[1], "fished_at": fished, "trip_stop_id": sid},
        headers=device,
    )
    assert r.status_code == 400
    # 남의 계획 장소로는 연결 불가
    other = signup(client)
    r = client.post(
        "/api/v1/journals",
        json={"place_id": places[0], "fished_at": fished, "trip_stop_id": sid},
        headers=other,
    )
    assert r.status_code == 400
    r = client.post(
        "/api/v1/journals",
        json={"place_id": places[0], "fished_at": fished, "trip_stop_id": sid},
        headers=device,
    )
    assert r.status_code == 201, r.text
    jid = r.json()["journal"]["id"]
    assert r.json()["journal"]["trip_stop_id"] == sid
    t2 = client.get(f"{URL}/{t['id']}", headers=device).json()
    assert t2["stops"][0]["journal_ids"] == [jid]
    # 수정할 때 trip_stop_id 를 안 보내면 연결 유지
    r = client.put(
        f"/api/v1/journals/{jid}",
        json={"place_id": places[0], "fished_at": fished, "memo": "수정"},
        headers=device,
    )
    assert r.json()["journal"]["trip_stop_id"] == sid
    # 장소를 지우면 기록은 남고 연결만 끊긴다
    client.delete(f"{URL}/{t['id']}/stops/{sid}", headers=device)
    j = client.get(f"/api/v1/journals/{jid}", headers=device).json()
    assert j["trip_stop_id"] is None


def test_account_delete_removes_trips(client, places):
    h = signup(client)
    client.post(
        URL,
        json={"start_date": _d(1), "end_date": _d(1), "stops": [{"day": _d(1), "place_id": places[0]}]},
        headers=h,
    )
    assert client.delete("/api/v1/me/account", headers=h).status_code == 204
    from sqlalchemy import func, select

    from app.core.db import SessionLocal
    from app.models import Account, TripPlan

    with SessionLocal() as db:
        # 탈퇴한 계정의 사용자 ID 로 남은 계획이 없어야 한다
        uids = db.scalars(select(Account.user_id).where(Account.deleted_at.is_not(None))).all()
        assert db.scalar(select(func.count(TripPlan.id)).where(TripPlan.user_id.in_(uids))) == 0


def test_outlook_weather_and_detail_range(client, device):
    """TMP·POP·SKY·PTY 가 상세 API 와 출조계획 API 까지 전달된다.
    결측은 0 으로 바꾸지 않고, 기상청 코드는 그대로, 예보가 하루를 다 덮지 않는 날은 「자료 없음」"""
    from app.core.db import SessionLocal
    from app.core.timeutil import kst_day_range
    from app.models import OceanReading, Place, PlaceStation, Region, Station
    from app.models.base import utcnow
    from app.models.enums import DataKind, Metric, StationKind, StationRole

    day = today_kst() + timedelta(days=1)
    lo, _ = kst_day_range(day)
    now = utcnow()
    with SessionLocal() as db:
        r = Region(name="충남 보령시")
        p = Place(name="날씨-테스트", lat=36.3, lon=126.5)
        r.places = [p]
        grid = Station(provider="KMA", external_id="9,9", name="날씨 격자", kind=StationKind.KMA)
        db.add_all([r, grid])
        db.flush()
        db.add(PlaceStation(place_id=p.id, role=StationRole.FORECAST, station_id=grid.id, distance_km=1.0))
        # 내일 00~23시 + 모레 00시 한 점
        for h in range(25):
            t = lo + timedelta(hours=h)
            vals = {
                (Metric.WAVE_HEIGHT, "m"): 0.5,
                (Metric.WIND_SPEED, "m/s"): 3.0,
                # 10시 기온 결측
                (Metric.AIR_TEMP, "°C"): None if h == 10 else 8.0 + h % 6,
                (Metric.PRECIPITATION_PROBABILITY, "%"): 60.0 if h == 15 else 0.0,
                (Metric.SKY_STATE, "code"): 4.0 if h >= 12 else 1.0,
                # 0 없음 · 1 비 · 4 소나기
                (Metric.PRECIPITATION_TYPE, "code"): 1.0 if h == 15 else 4.0 if h == 16 else 0.0,
            }
            for (metric, unit), v in vals.items():
                db.add(OceanReading(station_id=grid.id, metric=metric, kind=DataKind.FORECAST, t=t, value=v,
                                    unit=unit, issued_at=now, fetched_at=now))
        db.commit()
        pid = p.id

    # 상세 API: 원 값·코드 그대로, 결측은 None
    pc = client.get(f"/api/v1/places/{pid}/conditions", params={"date": str(day)}).json()["place"]
    ser = {(s["metric"], s["kind"]): s for s in pc["series"]}
    temp = ser[("air_temp", "forecast")]
    assert temp["status"] == "ok" and len(temp["points"]) == 24
    assert [x["v"] for x in temp["points"]][10] is None  # 0 으로 채우지 않음
    assert {x["v"] for x in ser[("precipitation_type", "forecast")]["points"]} == {0.0, 1.0, 4.0}
    assert {x["v"] for x in ser[("sky_state", "forecast")]["points"]} == {1.0, 4.0}

    # 모레: 00시 한 점뿐 → 하루 예보처럼 보이지 않게 자료 없음
    pc2 = client.get(f"/api/v1/places/{pid}/conditions", params={"date": str(day + timedelta(days=1))}).json()
    ser2 = {(s["metric"], s["kind"]): s for s in pc2["place"]["series"]}
    for m in ("air_temp", "precipitation_probability", "sky_state", "precipitation_type"):
        x = ser2[(m, "forecast")]
        assert x["status"] == "unavailable" and x["reason"] == "NO_DATA"

    # 출조계획 API: 내일 계획 → 기온 최저·최고, 강수확률 최대, 강수형태(0 제외)
    t = client.post(
        URL,
        json={"start_date": str(day), "end_date": str(day), "stops": [{"day": str(day), "place_id": pid}]},
        headers=device,
    ).json()
    s = client.get(f"{URL}/{t['id']}/outlook", headers=device).json()["stops"][0]
    assert s["forecast_status"] == "available"
    assert s["air_temp_fc_min"]["v"] == 8.0 and s["air_temp_fc_max"]["v"] == 13.0
    assert s["pop_fc_max"]["v"] == 60.0
    assert s["precipitation_types"] == [1, 4]
