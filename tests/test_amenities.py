"""주변 편의시설 (편의점·주차장·공중화장실) — 카카오 호출은 가짜로"""

import httpx

from app.routers import amenities, rock_points


def _fake(monkeypatch, calls):
    def get(url, params=None, headers=None, timeout=None):
        calls.append((url.rsplit("/", 1)[-1], params.get("category_group_code") or params.get("query")))
        base = {"x": "129.1", "y": "35.1", "distance": "300", "address_name": "부산 해운대구"}
        if params.get("query") == "공중화장실":
            docs = [
                {**base, "place_name": "청사포 공중화장실", "category_name": "가정,생활 > 화장실"},
                {**base, "place_name": "화장실 리모델링", "category_name": "서비스,산업 > 인테리어"},
            ]
        else:
            docs = [{**base, "place_name": f"{params['category_group_code']}-{i}"} for i in range(5)]
        return httpx.Response(200, json={"documents": docs}, request=httpx.Request("GET", url))

    monkeypatch.setattr(amenities.get_settings(), "kakao_rest_key", "test")
    monkeypatch.setattr(amenities.httpx, "get", get)
    amenities._cache.clear()


def test_rock_amenities(client, monkeypatch):
    calls = []
    _fake(monkeypatch, calls)
    rock_points._data.cache_clear()
    pid = rock_points._data()["points"][0]["id"]
    d = client.get(f"/api/v1/rock-points/{pid}/amenities").json()
    assert len(d["stores"]) == 3 and len(d["parking"]) == 3  # 종류별 3곳까지
    assert [t["name"] for t in d["toilets"]] == ["청사포 공중화장실"]  # 화장실 분류만
    assert sorted(c[1] for c in calls) == ["CS2", "PK6", "공중화장실"]
    client.get(f"/api/v1/rock-points/{pid}/amenities")
    assert len(calls) == 3  # 두 번째는 캐시
    assert client.get("/api/v1/rock-points/99999999/amenities").status_code == 404


def test_place_amenities_and_no_key(client, monkeypatch, places):
    calls = []
    _fake(monkeypatch, calls)
    r = client.get(f"/api/v1/places/{places[0]}/amenities")
    assert r.status_code == 200
    monkeypatch.setattr(amenities.get_settings(), "kakao_rest_key", "")
    amenities._cache.clear()
    assert client.get(f"/api/v1/places/{places[0]}/amenities").status_code in (200, 503)
    assert client.get("/api/v1/places/99999999/amenities").status_code == 404
