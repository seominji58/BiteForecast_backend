"""푸시 알림: 폰 등록·설정 API, 알림 규칙(즐겨찾기 좋음·이번 주 좋은 날·출조 날 특보), 중복 방지"""

import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.core.db import SessionLocal
from app.models import FishingIndex, Place, PlaceStation, PushDevice, Region, Station
from app.models.base import utcnow
from app.models.enums import StationKind, StationRole
from app.services import fcm, push, warning
from tests.conftest import signup

KST = ZoneInfo("Asia/Seoul")
DEV = "/api/v1/me/push/device"
PREFS = "/api/v1/me/push/prefs"


@pytest.fixture()
def outbox(monkeypatch):
    sent: list[tuple[list[str], fcm.Message]] = []
    monkeypatch.setattr(fcm, "enabled", lambda: True)
    monkeypatch.setattr(
        fcm, "send", lambda tokens, msg, http=None: (sent.append((tokens, msg)), (len(tokens), []))[1]
    )
    return sent


def _mine(outbox, token):
    return [m for toks, m in outbox if token in toks]


def _user_with_place(client, grades: dict[date, str]):
    """즐겨찾기 1곳 + 폰 등록한 새 사용자. grades: 날짜 → 그 지점 공식 지수"""
    h = signup(client)
    with SessionLocal() as db:
        st = Station(
            provider="KHOA",
            external_id=f"PUSH{uuid.uuid4().hex[:6]}",
            name="지점",
            kind=StationKind.FISHING_INDEX,
        )
        r = Region(name="테스트")
        p = Place(name=f"방파제{uuid.uuid4().hex[:4]}", lat=34.6, lon=127.7)
        r.places = [p]
        db.add_all([st, r])
        db.flush()
        db.add(PlaceStation(place_id=p.id, role=StationRole.FISHING_INDEX, station_id=st.id, distance_km=1.0))
        for d, g in grades.items():
            db.add(
                FishingIndex(
                    station_id=st.id, day=d, period="오전", species="감성돔", index=g, fetched_at=utcnow()
                )
            )
            db.add(
                FishingIndex(
                    station_id=st.id, day=d, period="오후", species="우럭", index="보통", fetched_at=utcnow()
                )
            )
        db.commit()
        pid, pname = p.id, p.name
    assert client.put(f"/api/v1/me/favorites/{pid}", headers=h).status_code == 204
    token = f"tok-{uuid.uuid4().hex}"
    assert client.put(DEV, json={"token": token, "platform": "android"}, headers=h).status_code == 204
    return h, token, pid, pname


def test_device_and_prefs_api(client):
    a, b = signup(client), signup(client)
    assert client.put(DEV, json={"token": "t" * 20, "platform": "android"}).status_code == 401
    assert client.put(DEV, json={"token": "t" * 20, "platform": "android"}, headers=a).status_code == 204
    # 같은 폰이 다른 계정으로 로그인 → 그 계정으로 옮김 (한 줄 유지)
    assert client.put(DEV, json={"token": "t" * 20, "platform": "android"}, headers=b).status_code == 204
    with SessionLocal() as db:
        rows = db.query(PushDevice).filter(PushDevice.token == "t" * 20).all()
        assert len(rows) == 1
    # 다른 사람 폰은 못 지움
    client.post(f"{DEV}/remove", json={"token": "t" * 20}, headers=a)
    with SessionLocal() as db:
        assert db.query(PushDevice).filter(PushDevice.token == "t" * 20).count() == 1
    client.post(f"{DEV}/remove", json={"token": "t" * 20}, headers=b)
    with SessionLocal() as db:
        assert db.query(PushDevice).filter(PushDevice.token == "t" * 20).count() == 0

    assert client.get(PREFS, headers=a).json() == {
        "fav_good": True,
        "trip_warning": True,
        "weekly_best": True,
    }
    r = client.patch(PREFS, json={"weekly_best": False}, headers=a).json()
    assert r == {"fav_good": True, "trip_warning": True, "weekly_best": False}
    assert client.get(PREFS, headers=a).json()["weekly_best"] is False


def test_fav_good_evening_once(client, outbox):
    evening = datetime(2026, 11, 25, 18, 30, tzinfo=KST)
    tomorrow = evening.date() + timedelta(days=1)
    h, token, pid, pname = _user_with_place(client, {tomorrow: "좋음"})

    with SessionLocal() as db:
        push.run(db, evening.replace(hour=14))  # 낮에는 보내지 않음
    assert _mine(outbox, token) == []

    with SessionLocal() as db:
        push.run(db, evening)
    [msg] = _mine(outbox, token)
    assert pname in msg.title and "좋음" in msg.title
    assert msg.data == {"url": f"/place/{pid}"}

    with SessionLocal() as db:
        push.run(db, evening.replace(hour=19))  # 다음 시간에도 다시 안 보냄
    assert len(_mine(outbox, token)) == 1


def test_fav_good_skips_normal_and_pref_off(client, outbox):
    evening = datetime(2026, 11, 25, 19, 0, tzinfo=KST)
    tomorrow = evening.date() + timedelta(days=1)
    _, t1, *_ = _user_with_place(client, {tomorrow: "보통"})
    h2, t2, *_ = _user_with_place(client, {tomorrow: "매우좋음"})
    client.patch(PREFS, json={"fav_good": False}, headers=h2)
    with SessionLocal() as db:
        push.run(db, evening)
    assert _mine(outbox, t1) == [] and _mine(outbox, t2) == []


def test_weekly_best_monday(client, outbox):
    monday = datetime(2026, 11, 30, 9, 0, tzinfo=KST)
    days = [monday.date() + timedelta(days=i) for i in range(7)]
    _, token, *_ = _user_with_place(client, {days[1]: "좋음", days[4]: "매우좋음", days[5]: "나쁨"})
    with SessionLocal() as db:
        push.run(db, monday.replace(day=1, month=12))  # 화요일은 안 보냄
    assert _mine(outbox, token) == []
    with SessionLocal() as db:
        push.run(db, monday)
        push.run(db, monday.replace(hour=10))
    [msg] = _mine(outbox, token)
    assert "12/4(금)" in msg.title  # 좋음 이상 1곳씩이면 등급이 높은 날


def test_trip_warning_to_owner_and_members(client, places, outbox, monkeypatch):
    now = datetime.now(KST).replace(hour=10)
    owner, friend = signup(client), signup(client)
    day = str(now.date() + timedelta(days=1))
    t = client.post(
        "/api/v1/me/trips",
        json={"start_date": day, "end_date": day, "stops": [{"day": day, "place_id": places[0]}]},
        headers=owner,
    ).json()
    code = client.post(f"/api/v1/me/trips/{t['id']}/invite", headers=owner).json()["code"]
    client.post(f"/api/v1/trip-invites/{code}/join", headers=friend)
    toks = {}
    for name, h in (("owner", owner), ("friend", friend)):
        toks[name] = f"tok-{uuid.uuid4().hex}"
        client.put(DEV, json={"token": toks[name], "platform": "android"}, headers=h)

    calm = SimpleNamespace(level="none", active=[])
    storm = SimpleNamespace(level="warning", active=[SimpleNamespace(type="풍랑주의보", severe=True)])
    monkeypatch.setattr(warning, "latest_snapshot", lambda db: None)
    monkeypatch.setattr(warning, "evaluate", lambda db, place, snap=None, health=None: calm)
    with SessionLocal() as db:
        push.run(db, now)
    assert _mine(outbox, toks["owner"]) == []

    monkeypatch.setattr(warning, "evaluate", lambda db, place, snap=None, health=None: storm)
    with SessionLocal() as db:
        push.run(db, now)
        push.run(db, now.replace(hour=11))
    for name in ("owner", "friend"):
        [msg] = _mine(outbox, toks[name])
        assert msg.title == "내일 출조지에 풍랑주의보"
        assert msg.data == {"url": f"/trip/{t['id']}"}


def test_no_key_counts_but_sends_nothing(client, monkeypatch):
    called = []
    monkeypatch.setattr(fcm, "send", lambda *a, **k: called.append(1) or (0, []))
    evening = datetime(2026, 11, 25, 18, 0, tzinfo=KST)
    _user_with_place(client, {evening.date() + timedelta(days=1): "좋음"})
    with SessionLocal() as db:
        stats = push.run(db, evening)
    assert stats.get("fav_good_due", 0) >= 1 and called == []


def test_legal_pages(client):
    for path, title in (("/privacy", "개인정보 처리방침"), ("/terms", "이용약관")):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
        assert title in r.text and "biteforecast@outlook.kr" in r.text
    assert "국외 이전" in client.get("/privacy").text
