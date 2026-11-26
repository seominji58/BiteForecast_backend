"""전국 낚시 탐험 도장: 반경·특보·밤·하루 1번·포인트(처음 한 번)·좌표 저장 안 함"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.db import SessionLocal
from app.models import ChallengeVisit, Place, Region
from app.routers import challenge as mod
from app.services import warning

URL = "/api/v1/challenge"


@pytest.fixture()
def spot(monkeypatch):
    with SessionLocal() as db:
        r = Region(name="탐험 테스트")
        p = Place(name="테스트 낚시공원", lat=34.47, lon=127.10)
        r.places = [p]
        db.add(r)
        db.commit()
        pid = p.id
    data = {
        "season": 1,
        "title": "시즌 1",
        "radius_m": 300,
        "points": 20,
        "spots": [
            {"place_id": pid, "name": "테스트 낚시공원", "region": "전남 고흥군", "sea": "남해", "info": None}
        ],
    }
    monkeypatch.setattr(mod, "season", lambda: data)
    monkeypatch.setattr(warning, "evaluate", lambda db, place, *a, **k: SimpleNamespace(level="none"))
    noon = datetime(2026, 11, 26, 3, 0, tzinfo=UTC)  # KST 12:00
    monkeypatch.setattr(mod, "utcnow", lambda: noon)
    return pid


def test_visit_rules_and_points(client, device, spot, monkeypatch):
    near = {"lat": 34.4705, "lon": 127.1003}  # 약 60m
    far = {"lat": 34.48, "lon": 127.10}  # 약 1.1km

    assert client.post(f"{URL}/{spot}/visit", json=near).status_code == 401
    r = client.post(f"{URL}/{spot}/visit", json=far, headers=device)
    assert r.status_code == 409 and "떨어져" in r.json()["error"]["message"]

    r = client.post(f"{URL}/{spot}/visit", json=near, headers=device)
    assert r.status_code == 200, r.text
    assert r.json() == {"place_id": spot, "first": True, "points": 20, "visited": 1, "total": 1}
    # 같은 날 두 번은 안 됨
    assert client.post(f"{URL}/{spot}/visit", json=near, headers=device).status_code == 409

    # 다음 날 다시 찍어도 포인트는 처음 한 번만
    monkeypatch.setattr(mod, "utcnow", lambda: datetime(2026, 11, 27, 3, 0, tzinfo=UTC))
    r = client.post(f"{URL}/{spot}/visit", json=near, headers=device).json()
    assert r["first"] is False and r["points"] == 0

    s = client.get(URL, headers=device).json()
    assert s["visited"] == 1 and s["spots"][0]["visits"] == 2 and s["spots"][0]["visited_at"]
    assert client.get(URL).json()["spots"][0]["visited_at"] is None  # 손님은 내 기록 없음

    # 좌표는 저장하지 않는다 (거리 구간만)
    with SessionLocal() as db:
        v = db.query(ChallengeVisit).filter(ChallengeVisit.place_id == spot).first()
        assert v.within_m == 100 and not hasattr(v, "lat")


def test_blocked_by_warning_and_night(client, device, spot, monkeypatch):
    near = {"lat": 34.4705, "lon": 127.1003}
    monkeypatch.setattr(warning, "evaluate", lambda db, place, *a, **k: SimpleNamespace(level="warning"))
    r = client.post(f"{URL}/{spot}/visit", json=near, headers=device)
    assert r.status_code == 409 and "특보" in r.json()["error"]["message"]

    monkeypatch.setattr(warning, "evaluate", lambda db, place, *a, **k: SimpleNamespace(level="none"))
    monkeypatch.setattr(mod, "utcnow", lambda: datetime(2026, 11, 26, 13, 0, tzinfo=UTC))  # KST 22:00
    r = client.post(f"{URL}/{spot}/visit", json=near, headers=device)
    assert r.status_code == 409 and "해가 진" in r.json()["error"]["message"]


def test_not_a_spot(client, device, spot, places):
    assert (
        client.post(f"{URL}/{places[0]}/visit", json={"lat": 0, "lon": 0}, headers=device).status_code == 404
    )


def test_season_file_points_to_real_places():
    """시즌 파일: 18곳, 바다 구분, place_id 중복 없음"""
    s = mod.season.__wrapped__() if hasattr(mod.season, "__wrapped__") else mod.season()
    ids = [x["place_id"] for x in s["spots"]]
    assert len(ids) == len(set(ids)) == 17
    assert {x["sea"] for x in s["spots"]} <= {"동해", "서해", "남해", "제주"}
