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
