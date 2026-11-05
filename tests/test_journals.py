"""낚시일지 · 포인트 · 칭호 · 환경정보 연결 테스트 (TC-04, TC-05, TC-06)"""

from datetime import UTC, datetime, timedelta

from app.core.db import SessionLocal
from app.models import PlaceStation, Station, TideForecast
from app.models.enums import StationKind, StationRole
from tests.conftest import ADMIN, upload

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


# --- 포인트 (FR-11): 인증 완료 일지만 지급 (재설계 v2 §9) ---


def total(client, device) -> int:
    return client.get("/api/v1/me/points", headers=device).json()["total_points"]


def verified(client, device, **kw) -> dict:
    """사진을 올리고 「저장하고 인증 신청」 → 관리자 승인까지 마친 일지"""
    kw.setdefault("species_code", "rockfish")
    photo = upload(client, device, color=(len(str(kw)) * 7 % 255, 90, 120))
    j = create(client, device, photo_ids=[photo["id"]], request_verification=True, **kw)["journal"]
    assert j["verification"]["status"] == "pending"
    res = client.post(f"/api/v1/admin/verifications/{j['id']}/approve", headers=ADMIN)
    assert res.status_code == 200, res.text
    return j


def test_no_points_without_verification(client, device, places):
    """저장만 하거나 사진만 올려서는 포인트가 없다"""
    out = create(client, device, place_id=places[0], species_code="rockfish", max_length_cm=30)
    assert out["point_delta"] == 0 and out["journal"]["verification"]["status"] == "none"
    photo = upload(client, device)
    out = create(client, device, place_id=places[0], photo_ids=[photo["id"]])
    assert out["point_delta"] == 0 and out["journal"]["photo_count"] == 1
    # 인증 신청(대기)만으로도 없음
    jid = out["journal"]["id"]
    res = client.put(
        f"{URL}/{jid}",
        json=body(
            place_id=places[0], species_code="rockfish", photo_ids=[photo["id"]], request_verification=True
        ),
        headers=device,
    ).json()
    assert res["journal"]["verification"]["status"] == "pending" and res["point_delta"] == 0
    assert total(client, device) == 0


def test_points_basic(client, device, places):
    # 승인: 작성 10 + 첫 장소 15
    verified(client, device, place_id=places[0])
    assert total(client, device) == 25
    # 같은 장소 두 번째: 작성 10 + 어종·크기 5
    verified(client, device, place_id=places[0], when="2026-11-02T06:00:00+09:00", max_length_cm=30)
    assert total(client, device) == 40


def test_double_approve_and_resave_do_not_double_award(client, device, places):
    """TC-05: 같은 기록을 여러 번 승인하거나 그대로 다시 저장해도 한 번만 반영"""
    j = verified(client, device, place_id=places[0], species_code="mackerel", max_length_cm=25)
    t = total(client, device)
    for _ in range(3):
        assert client.post(f"/api/v1/admin/verifications/{j['id']}/approve", headers=ADMIN).status_code == 200
    assert total(client, device) == t
    same = body(place_id=places[0], species_code="mackerel", max_length_cm=25)
    res = client.put(f"{URL}/{j['id']}", json=same, headers=device).json()  # photo_ids 없음 = 사진 변경 없음
    assert res["point_delta"] == 0 and res["journal"]["verification"]["status"] == "approved"


def test_reject_and_edit_revoke_points(client, device, places):
    """반려되면 회수 + 사유 표시, 인증 내용 수정 시 다시 검토 대기(포인트 회수)"""
    j = verified(client, device, place_id=places[1], max_length_cm=40)
    assert total(client, device) == 30
    res = client.post(
        f"/api/v1/admin/verifications/{j['id']}/reject",
        json={"reason": "물고기가 보이지 않아요"},
        headers=ADMIN,
    )
    assert res.status_code == 200
    assert total(client, device) == 0
    got = client.get(f"{URL}/{j['id']}", headers=device).json()["verification"]
    assert got["status"] == "rejected" and got["reject_reason"] == "물고기가 보이지 않아요"

    # 다시 신청 → 승인
    assert (
        client.post(f"{URL}/{j['id']}/verification", headers=device).json()["verification"]["status"]
        == "pending"
    )
    client.post(f"/api/v1/admin/verifications/{j['id']}/approve", headers=ADMIN)
    assert total(client, device) == 30
    # 길이 수정 → 대기로 돌아가고 포인트 회수
    res = client.put(
        f"{URL}/{j['id']}",
        json=body(place_id=places[1], species_code="rockfish", max_length_cm=45),
        headers=device,
    ).json()
    assert res["journal"]["verification"]["status"] == "pending" and res["point_delta"] == -30


def test_delete_recalculates_and_moves_first_place(client, device, places):
    """TC-06: 삭제 시 회수, 첫 장소 보너스는 다음 인증 일지로 이전"""
    first = verified(client, device, place_id=places[1], when="2026-11-01T06:00:00+09:00")
    verified(client, device, place_id=places[1], when="2026-11-03T06:00:00+09:00")
    assert total(client, device) == 35

    res = client.delete(f"{URL}/{first['id']}", headers=device).json()
    assert res["journal"] is None
    assert res["point_delta"] == -10  # 작성 포인트만 회수, 첫 장소 15P 는 남은 일지로 이전
    assert res["total_points"] == 25


def test_personal_best(client, device, places):
    p = places[2]
    verified(
        client, device, place_id=p, when="2026-10-01T06:00:00+09:00", species_code="seabass", max_length_cm=40
    )
    # 같은 어종 기록 갱신 → +35 (작성 10 + 어종·크기 5 + 최대어 20)
    before = total(client, device)
    verified(
        client, device, place_id=p, when="2026-10-05T06:00:00+09:00", species_code="seabass", max_length_cm=55
    )
    assert total(client, device) - before == 35


def test_title_changes_on_threshold(client, device, places):
    """칭호: 50P 도달 시 초보, 일지 삭제로 50P 미만이 되면 다시 입문"""
    verified(client, device, place_id=places[0], species_code="mullet", max_length_cm=40)  # 30P
    b = verified(client, device, place_id=places[1], species_code="mullet", max_length_cm=30)  # +30P
    title = client.get("/api/v1/me/title", headers=device).json()
    assert title["total_points"] == 60 and title["current"]["name"] == "초보"

    res = client.delete(f"{URL}/{b['id']}", headers=device).json()
    assert res["title"]["current"]["name"] == "입문" and res["title_changed"] is True


def test_verification_requires_photo_and_species(client, device, places):
    j = create(client, device, place_id=places[0])["journal"]
    assert j["verification"]["can_request"] is False
    assert set(j["verification"]["missing"]) == {"사진 1장 이상", "어종"}
    res = client.post(f"{URL}/{j['id']}/verification", headers=device)
    assert res.status_code == 400
    # 저장과 함께 신청해도 조건이 없으면 거절 (저장 자체가 실패)
    res = client.post(URL, json=body(place_id=places[0], request_verification=True), headers=device)
    assert res.status_code == 400


def test_cancel_pending(client, device, places):
    photo = upload(client, device)
    j = create(
        client,
        device,
        place_id=places[0],
        species_etc="쥐노래미",
        photo_ids=[photo["id"]],
        request_verification=True,
    )["journal"]
    res = client.delete(f"{URL}/{j['id']}/verification", headers=device).json()
    assert res["verification"]["status"] == "none"
    assert client.delete(f"{URL}/{j['id']}/verification", headers=device).status_code == 400


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
