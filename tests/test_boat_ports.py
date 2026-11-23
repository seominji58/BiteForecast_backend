"""낚시어선 출항항"""

import httpx

from app.routers import boat_ports, nearby


def test_list_and_nearby(client, monkeypatch):
    boat_ports._data.cache_clear()
    d = client.get("/api/v1/boat-ports").json()
    assert d["boats_total"] > 4000 and len(d["ports"]) > 400
    top = d["ports"][0]
    assert top["id"] == 1 and top["boats"] >= d["ports"][1]["boats"]
    assert "연락처" in d["notice"]
    seen = {}

    def get(url, params=None, headers=None, timeout=None):
        seen.update(params)
        return httpx.Response(200, json={"documents": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(nearby.get_settings(), "kakao_rest_key", "test")
    monkeypatch.setattr(nearby.httpx, "get", get)
    nearby._cache.clear()
    r = client.get(f"/api/v1/boat-ports/{top['id']}/nearby")
    assert r.status_code == 200 and seen["x"] == top["lon"]
    assert client.get("/api/v1/boat-ports/999999/nearby").status_code == 404
