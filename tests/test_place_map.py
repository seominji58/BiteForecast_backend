"""낚시터 위성 사진 (네이버 Static Map 대행): 이미지 · 바다 지점은 멀리서 · 404·503·502 · 캐시"""

from app.core.db import SessionLocal
from app.models import Place, Region
from app.routers import place_map

URL = "/api/v1/places/{}/map.jpg"


def _place(lat=37.28, lon=126.60, type_="paid") -> int:
    with SessionLocal() as db:
        region = Region(name="위성 테스트 해역")
        region.places = [Place(name="위성 테스트 낚시터", lat=lat, lon=lon, type=type_)]
        db.add(region)
        db.commit()
        return region.places[0].id


def _fake(monkeypatch, calls, content_type="image/jpeg"):
    class R:
        headers = {"content-type": content_type}
        content = b"\xff\xd8jpeg"

        def raise_for_status(self):
            pass

    def get(url, params, headers, timeout):
        calls.append(params)
        assert "X-NCP-APIGW-API-KEY" in headers
        return R()

    s = place_map.get_settings()
    monkeypatch.setattr(s, "ncp_map_client_id", "id")
    monkeypatch.setattr(s, "ncp_map_client_secret", "secret")
    monkeypatch.setattr(place_map.httpx, "get", get)
    place_map._cache.clear()


def test_returns_image_and_caches(client, monkeypatch):
    pid = _place()
    calls: list[dict] = []
    _fake(monkeypatch, calls)
    r = client.get(URL.format(pid), params={"size": "thumb"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content.startswith(b"\xff\xd8") and "max-age" in r.headers["cache-control"]
    assert calls[0]["maptype"] == "satellite" and calls[0]["w"] == 160
    client.get(URL.format(pid), params={"size": "thumb"})
    assert len(calls) == 1


def test_sea_point_uses_far_view(client, monkeypatch):
    pid = _place(type_="boat")
    calls: list[dict] = []
    _fake(monkeypatch, calls)
    assert client.get(URL.format(pid)).status_code == 200
    assert calls[0]["level"] < 16


def test_no_coords_404_no_key_503_bad_upstream_502(client, monkeypatch):
    calls: list[dict] = []
    _fake(monkeypatch, calls)
    assert client.get(URL.format(_place(lat=None, lon=None))).status_code == 404
    assert calls == []

    _fake(monkeypatch, calls, content_type="application/json")
    assert client.get(URL.format(_place())).status_code == 502

    monkeypatch.setattr(place_map.get_settings(), "ncp_map_client_id", "")
    assert client.get(URL.format(_place())).status_code == 503
