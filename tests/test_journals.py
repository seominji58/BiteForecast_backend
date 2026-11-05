"""낚시일지 · 포인트 · 칭호 · 환경정보 연결 테스트 (TC-04, TC-05, TC-06)"""

from datetime import UTC, datetime, timedelta

from app.core.db import SessionLocal
from app.models import PlaceStation, Station, TideForecast
from app.models.enums import StationKind, StationRole

URL = "/api/v1/journals"


def body(place_id: int, when: str = "2026-11-01T06:00:00+09:00", **kw) -> dict:
    return {"place_id": place_id, "fished_at": when, **kw}


def create(client, device, **kw):
    res = client.post(URL, json=body(**kw), headers=device)
    assert res.status_code == 201, res.text
    return res.json()


# --- 기본 CRUD (TC-04) ---


def test_create_and_list(client, device, places):
    out = create(client, device, place_id=places[0], count=3, species_code="rockfish", max_length_cm=32.44)
    j = out["journal"]
    assert j["place_name"] == "테스트 장소 0"
    assert j["species_name"] == "우럭(조피볼락)"
    assert j["max_length_cm"] == 32.4  # 소수 1자리
    assert j["fished_at"] == "2026-10-31T21:00:00Z"  # UTC 로 저장·응답

    listed = client.get(URL, headers=device).json()
    assert [x["id"] for x in listed] == [j["id"]]


def test_other_user_cannot_see_journal(client, device, places):
    j = create(client, device, place_id=places[0])["journal"]
    other = {"X-Device-Id": "00000000-0000-4000-8000-000000000000"}
    assert client.get(f"{URL}/{j['id']}", headers=other).status_code == 404
    assert client.delete(f"{URL}/{j['id']}", headers=other).status_code == 404


def test_validation(client, device, places):
    def post(**kw):
        return client.post(URL, json=body(place_id=places[0], **kw), headers=device)

    assert post(count=-1).status_code == 422  # 마릿수 음수 금지
    assert post(max_length_cm=0).status_code == 422
    assert post(max_length_cm=301).status_code == 422
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert post(when=future).status_code == 422
    assert post(when="2026-11-01T06:00:00").status_code == 422  # timezone 없음
    assert post(species_code="rockfish", species_etc="우럭").status_code == 422
    assert post(species_code="unknown").status_code == 400
    assert client.post(URL, json=body(place_id=99999), headers=device).status_code == 400


# --- 포인트 (FR-11) ---


def test_points_basic(client, device, places):
    # 작성 10 + 첫 장소 15
    assert create(client, device, place_id=places[0])["point_delta"] == 25
    # 같은 장소 두 번째: 작성 10 + 어종·크기 5
    out = create(
        client,
        device,
        place_id=places[0],
        when="2026-11-02T06:00:00+09:00",
        species_code="rockfish",
        max_length_cm=30,
    )
    assert out["point_delta"] == 15
    assert out["total_points"] == 40


def test_resave_does_not_double_award(client, device, places):
    """TC-05: 동일 일지 재저장 시 재적립 없음"""
    out = create(client, device, place_id=places[0], species_code="mackerel", max_length_cm=25)
    jid, total = out["journal"]["id"], out["total_points"]
    payload = body(place_id=places[0], species_code="mackerel", max_length_cm=25)
    for _ in range(3):
        res = client.put(f"{URL}/{jid}", json=payload, headers=device).json()
        assert res["point_delta"] == 0
        assert res["total_points"] == total


def test_delete_recalculates_and_moves_first_place(client, device, places):
    """TC-06: 삭제 시 회수, 첫 장소 보너스는 다음 일지로 이전"""
    first = create(client, device, place_id=places[1], when="2026-11-01T06:00:00+09:00")["journal"]
    create(client, device, place_id=places[1], when="2026-11-03T06:00:00+09:00")
    assert client.get("/api/v1/me/points", headers=device).json()["total_points"] == 35

    res = client.delete(f"{URL}/{first['id']}", headers=device).json()
    assert res["journal"] is None
    assert res["point_delta"] == -10  # 작성 포인트만 회수, 첫 장소 15P 는 남은 일지로 이전
    assert res["total_points"] == 25


def test_personal_best(client, device, places):
    p = places[2]
    create(
        client, device, place_id=p, when="2026-10-01T06:00:00+09:00", species_code="seabass", max_length_cm=40
    )
    # 같은 어종 기록 갱신 → +20 (작성 10 + 어종·크기 5 + 최대어 20)
    out = create(
        client, device, place_id=p, when="2026-10-05T06:00:00+09:00", species_code="seabass", max_length_cm=55
    )
    assert out["point_delta"] == 35
    # 갱신 기록을 더 작게 정정 → 최대어 20P 회수
    jid = out["journal"]["id"]
    res = client.put(
        f"{URL}/{jid}",
        json=body(place_id=p, when="2026-10-05T06:00:00+09:00", species_code="seabass", max_length_cm=35),
        headers=device,
    ).json()
    assert res["point_delta"] == -20


def test_title_changes_on_threshold(client, device, places):
    """칭호: 50P 도달 시 초보, 일지 삭제로 50P 미만이 되면 다시 입문"""
    a = create(client, device, place_id=places[0], species_code="mullet", max_length_cm=40)  # 30P
    assert a["title"]["current"]["name"] == "입문" and a["title_changed"] is False
    b = create(client, device, place_id=places[1], species_code="mullet", max_length_cm=30)  # +30P
    assert b["total_points"] == 60
    assert b["title"]["current"]["name"] == "초보" and b["title_changed"] is True

    res = client.delete(f"{URL}/{b['journal']['id']}", headers=device).json()
    assert res["title"]["current"]["name"] == "입문" and res["title_changed"] is True


# --- 환경정보 연결 (FR-10, TC-02) ---


def test_env_snapshot_is_null_without_station(client, device, places):
    j = create(client, device, place_id=places[0])["journal"]
    snaps = {s["metric"]: s for s in j["env_snapshots"]}
    assert set(snaps) == {"tide_level", "wave_height", "wind_speed", "water_temp"}
    assert all(s["value"] is None and s["kind"] is None for s in snaps.values())  # 0 이 아니라 null


def test_env_snapshot_links_nearest_tide(client, device, places):
    t0 = datetime(2026, 9, 1, 21, 0, tzinfo=UTC)  # = 2026-09-02 06:00 KST
    with SessionLocal() as db:
        st = Station(
            provider="KHOA", external_id="TEST_TIDE", name="테스트 조위관측소", kind=StationKind.TIDE
        )
        db.add(st)
        db.flush()
        db.add(PlaceStation(place_id=places[2], role=StationRole.TIDE, station_id=st.id, distance_km=4.2))
        for h, level in [(-2, 100.0), (0, 250.0), (1, 300.0)]:
            db.add(
                TideForecast(
                    station_id=st.id,
                    t=t0 + timedelta(hours=h),
                    level_cm=level,
                    issued_at=t0 - timedelta(days=1),
                    fetched_at=t0 - timedelta(days=1),
                )
            )
        db.commit()

    j = create(client, device, place_id=places[2], when="2026-09-02T06:10:00+09:00")["journal"]
    tide = next(s for s in j["env_snapshots"] if s["metric"] == "tide_level")
    assert tide["value"] == 250.0  # ±1시간 안에서 가장 가까운 06:00 값
    assert tide["kind"] == "forecast"
    assert tide["distance_km"] == 4.2
    assert tide["source_agency"] == "KHOA"
