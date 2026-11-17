"""지역 검색 (카카오 로컬 대행) — 키 없으면 503, 짧은 검색어 422, 응답 변환"""

from app.routers import geo


def test_short_query_rejected(client):
    assert client.get("/api/v1/geo/search", params={"q": "a"}).status_code == 422


def test_no_key_is_503(client, monkeypatch):
    monkeypatch.setattr(geo.get_settings(), "kakao_rest_key", "")
    assert client.get("/api/v1/geo/search", params={"q": "속초항"}).status_code == 503


def test_maps_kakao_documents(client, monkeypatch):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"documents": [{"place_name": "신진도", "address_name": "충남 태안군 근흥면 신진도리",
                                   "road_address_name": "", "x": "126.141", "y": "36.678", "category_name": "여행 > 섬"}]}

    monkeypatch.setattr(geo.get_settings(), "kakao_rest_key", "test")
    monkeypatch.setattr(geo.httpx, "get", lambda *a, **k: R())
    geo._cache.clear()
    out = client.get("/api/v1/geo/search", params={"q": "태안 신진도"}).json()
    assert out == [{"name": "신진도", "address": "충남 태안군 근흥면 신진도리", "lat": 36.678, "lon": 126.141, "category": "섬"}]
