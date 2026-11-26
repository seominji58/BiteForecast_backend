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


# --- 배낚시 항구 시즌 ---
@pytest.fixture()
def port(monkeypatch):
    data = {
        "season": 2,
        "title": "배낚시 항구",
        "radius_m": 500,
        "points": 20,
        "spots": [
            {
                "key": "테스트항|전남광주통합특별시 여수시",
                "name": "테스트항",
                "sgg": "전남광주통합특별시 여수시",
                "region": "전남 여수시",
                "sea": "남해",
                "lat": 34.72,
                "lon": 127.72,
                "boats": 10,
                "max_passengers": 20,
                "kakao_url": None,
                "note": "항구 안 낚시 금지",
            }
        ],
    }
    monkeypatch.setattr(mod, "port_season", lambda: data)
    seen = []

    def ev(db, place, *a, **k):
        seen.append(place)
        return SimpleNamespace(level="none")

    monkeypatch.setattr(warning, "evaluate", ev)
    # 새벽 5시(KST)도 찍을 수 있다 — 배낚시는 새벽 출항
    monkeypatch.setattr(mod, "utcnow", lambda: datetime(2026, 11, 25, 20, 0, tzinfo=UTC))
    return SimpleNamespace(key=data["spots"][0]["key"], seen=seen)


def test_port_visit(client, device, port):
    near = {"key": port.key, "lat": 34.7235, "lon": 127.7203}  # 약 400m
    r = client.post("/api/v1/challenge-ports/visit", json=near, headers=device)
    assert r.status_code == 200, r.text
    assert r.json()["first"] is True and r.json()["points"] == 20 and r.json()["total"] == 1
    # 특보 판정은 배낚시 기준(boat)으로
    assert str(port.seen[0].type) == "boat" and port.seen[0].region_name == "전남 여수시"
    assert (
        client.post("/api/v1/challenge-ports/visit", json=near, headers=device).status_code == 409
    )  # 하루 1번
    far = {"key": port.key, "lat": 34.75, "lon": 127.72}
    assert client.post("/api/v1/challenge-ports/visit", json=far, headers=device).status_code == 409
    bad = {"key": "없는항|x", "lat": 34.72, "lon": 127.72}
    assert client.post("/api/v1/challenge-ports/visit", json=bad, headers=device).status_code == 404
    s = client.get("/api/v1/challenge-ports", headers=device).json()
    assert s["visited"] == 1 and s["spots"][0]["note"] == "항구 안 낚시 금지"


def test_port_season_file():
    s = mod.port_season()
    keys = [x["key"] for x in s["spots"]]
    assert len(keys) == len(set(keys)) == 20 and s["radius_m"] == 500
    assert any(x["name"] == "장고항" and x["note"] for x in s["spots"])
