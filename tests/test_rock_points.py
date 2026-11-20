"""참고 포인트(해수부 갯바위): 자료 파일 형식 · 출입통제 제외 · 좌표 변환"""

import math

import httpx

from app.routers import rock_points
from scripts.build_rock_points import catches, utmk_to_wgs84


def test_endpoint(client):
    rock_points._data.cache_clear()
    r = client.get("/api/v1/rock-points")
    assert r.status_code == 200 and "max-age" in r.headers["cache-control"]
    d = r.json()
    assert "해양수산부" in d["source"] and "참고" in d["notice"] and len(d["points"]) > 1000
    p = d["points"][0]
    assert 32 < p["lat"] < 39 and 124 < p["lon"] < 132
    names = {x["name"].strip() for x in d["points"]}
    assert "황우리해안 갯바위" not in names  # 해경 출입통제구역(황우지해안) — 제외


def test_utmk_conversion():
    # 원점(127.5°E, 38°N) = (1,000,000, 2,000,000)
    lat, lon = utmk_to_wgs84(1_000_000, 2_000_000)
    assert math.isclose(lat, 38, abs_tol=1e-7) and math.isclose(lon, 127.5, abs_tol=1e-7)


def test_catches_parse():
    assert catches("▶감성돔 - 릴찌/ 장대 ▶농어 - 루어") == [
        {"species": "감성돔", "methods": ["릴찌", "장대"]},
        {"species": "농어", "methods": ["루어"]},
    ]


def test_near_address_attached_and_nearby(client, monkeypatch):
    """근처 주소가 붙고, 포인트 좌표로 주변 낚시점을 찾는다 (2026-11-20)"""
    from app.routers import nearby

    rock_points._data.cache_clear()
    pts = client.get("/api/v1/rock-points").json()["points"]
    with_addr = [p for p in pts if p.get("near_address")]
    assert len(with_addr) > 1000
    assert all(p["near_address_kind"] in ("address", "region") for p in with_addr)

    p = pts[0]
    seen = {}

    def get(url, params=None, headers=None, timeout=None):
        seen.update(params)
        return httpx.Response(200, json={"documents": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(nearby.get_settings(), "kakao_rest_key", "test")
    monkeypatch.setattr(nearby.httpx, "get", get)
    nearby._cache.clear()
    r = client.get(f"/api/v1/rock-points/{p['id']}/nearby")
    assert r.status_code == 200 and r.json()["shops"] == []
    assert seen["x"] == p["lon"] and seen["y"] == p["lat"]
    assert client.get("/api/v1/rock-points/99999999/nearby").status_code == 404


def test_near_requires_matching_coords():
    from app.services.near_address import near

    rock_points._data.cache_clear()
    p = rock_points._data()["points"][0]
    assert near("rock", p["id"], p["lat"], p["lon"]) is not None
    assert near("rock", p["id"], p["lat"] + 0.01, p["lon"]) is None  # 다른 곳의 같은 id → 붙이지 않음
