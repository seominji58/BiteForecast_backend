"""낚시터 근처 낚시점·낚시배 (카카오 반경 검색 대행): 분류 거르기 · 좌표 없으면 안 함 · 키 없음 503"""

from app.core.db import SessionLocal
from app.models import Place, Region
from app.routers import nearby

URL = "/api/v1/places/{}/nearby"


def _place(lat=37.28, lon=126.60) -> int:
    with SessionLocal() as db:
        region = Region(name="근처 테스트 해역")
        region.places = [Place(name="근처 테스트 낚시터", lat=lat, lon=lon)]
        db.add(region)
        db.commit()
        return region.places[0].id


def _doc(name, category, distance="1200", phone="032-000-0000"):
    return {
        "place_name": name,
        "category_name": category,
        "phone": phone,
        "address_name": "경기 안산시 단원구",
        "road_address_name": "",
        "x": "126.61",
        "y": "37.29",
        "distance": distance,
        "place_url": "http://place.map.kakao.com/1",
    }


def _fake(monkeypatch, docs_by_query, calls):
    class R:
        def __init__(self, docs):
            self.docs = docs

        def raise_for_status(self):
            pass

        def json(self):
            return {"documents": self.docs}

    def get(url, params, headers, timeout):
        calls.append(params["query"])
        return R(docs_by_query.get(params["query"], []))

    monkeypatch.setattr(nearby.get_settings(), "kakao_rest_key", "test")
    monkeypatch.setattr(nearby.httpx, "get", get)
    nearby._cache.clear()


def test_filters_by_category(client, monkeypatch):
    pid = _place()
    calls: list[str] = []
    _fake(
        monkeypatch,
        {
            "낚시점": [
                _doc("대부영흥낚시1번지", "스포츠,레저 > 스포츠용품 > 낚시용품", "2319"),
                _doc("길민박", "여행 > 숙박 > 민박", "2500"),
            ],
            "선상낚시": [
                _doc("은솔마린 태태호", "스포츠,레저 > 낚시", "8175", phone=""),
                _doc("해솔바다낚시터", "스포츠,레저 > 낚시 > 낚시터", "3998"),
            ],
        },
        calls,
    )
    out = client.get(URL.format(pid)).json()
    assert [s["name"] for s in out["shops"]] == ["대부영흥낚시1번지"]
    assert out["shops"][0]["category"] == "낚시용품" and out["shops"][0]["distance_m"] == 2319
    assert [b["name"] for b in out["boats"]] == ["은솔마린 태태호"]
    assert out["boats"][0]["phone"] is None and out["skipped"] is None

    # 같은 낚시터는 캐시 (카카오 호출 한도 보호)
    client.get(URL.format(pid))
    assert calls == ["낚시점", "선상낚시"]


def test_no_coords_is_skipped(client, monkeypatch):
    pid = _place(lat=None, lon=None)
    calls: list[str] = []
    _fake(monkeypatch, {}, calls)
    out = client.get(URL.format(pid)).json()
    assert out["shops"] == [] and out["boats"] == [] and out["skipped"]
    assert calls == []


def test_no_key_is_503_and_unknown_place_404(client, monkeypatch):
    pid = _place()
    monkeypatch.setattr(nearby.get_settings(), "kakao_rest_key", "")
    nearby._cache.clear()
    assert client.get(URL.format(pid)).status_code == 503
    assert client.get(URL.format(999999)).status_code == 404
