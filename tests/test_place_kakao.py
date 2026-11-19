"""카카오 장소 링크: 매칭된 곳만 · 없는 곳 404 · 매칭 기준(업종·거리·시군구)"""

from app.routers import place_kakao
from scripts.match_kakao_places import best_match

DATA = {
    7: {
        "name": "대부도바다낚시터",
        "url": "https://place.map.kakao.com/1",
        "road_address": "경기 안산시 단원구 x",
        "category": "낚시터",
        "phone": None,
        "moved": False,
    },
}


def test_endpoint(client, monkeypatch):
    monkeypatch.setattr(place_kakao, "_data", lambda: DATA)
    d = client.get("/api/v1/places/7/kakao").json()
    assert (
        d["url"].startswith("https://place.map.kakao.com") and d["source"] == "카카오" and d["moved"] is False
    )
    assert client.get("/api/v1/places/8/kakao").status_code == 404


def test_real_file_loads():
    place_kakao._data.cache_clear()
    assert all(v["url"].startswith("https://") for v in place_kakao._data().values())


P = {"name": "송정", "region_name": "부산 해운대구", "lat": 35.18, "lon": 129.2}


def doc(name, cat, lat=35.181, addr="부산 해운대구 송정동"):
    return {
        "place_name": name,
        "category_name": f"음식점 > {cat}",
        "address_name": addr,
        "road_address_name": "",
        "place_url": "http://place.map.kakao.com/2",
        "x": "129.2",
        "y": str(lat),
    }


def test_match_rules():
    assert best_match(P, [doc("송정집", "한식")]) is None  # 식당은 제외
    fishing = {**P, "name": "송정낚시터"}
    m = best_match(fishing, [doc("송정낚시터", "낚시터")])
    assert m and m["url"].startswith("https://") and m["move_m"] < 300
    assert best_match(fishing, [doc("송정낚시터", "낚시터", lat=35.25)]) is None  # 3km 넘게 떨어짐
    assert best_match(fishing, [doc("송정낚시터", "낚시터", addr="경남 거제시")]) is None  # 다른 시군구
