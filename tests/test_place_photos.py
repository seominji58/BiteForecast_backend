"""낚시터 실제 사진 (관광공사 매칭 파일): 목록 썸네일 · 상세 사진 · 없는 곳 404 · 출처 표시"""

from app.routers import place_photos

DATA = {
    7: {
        "title": "대부도바다낚시터",
        "license": "공공누리 제3유형 (출처 표시·변경 금지)",
        "images": [
            {"url": "https://t/a.jpg", "thumb": "https://t/a_s.jpg"},
            {"url": "https://t/b.jpg", "thumb": "https://t/b.jpg"},
        ],
    },
}


def test_index_and_detail(client, monkeypatch):
    monkeypatch.setattr(place_photos, "_data", lambda: DATA)
    idx = client.get("/api/v1/place-photos").json()
    assert idx["source"] == "한국관광공사" and idx["thumbs"] == {"7": "https://t/a_s.jpg"}
    d = client.get("/api/v1/places/7/photos").json()
    assert d["title"] == "대부도바다낚시터" and len(d["images"]) == 2 and "공공누리" in d["license"]
    assert client.get("/api/v1/places/8/photos").status_code == 404


def test_real_file_loads():
    place_photos._data.cache_clear()
    data = place_photos._data()
    assert all(v["images"] and v["images"][0]["url"].startswith("https://") for v in data.values())


def test_place_notices(client):
    """시드에 있는 곳은 안내 목록, 없는 곳은 빈 목록. 시군 통제구역은 목록 원문을 같이 준다"""
    import json
    from pathlib import Path

    d = json.loads((Path(__file__).resolve().parent.parent / "seeds" / "place_notices.json").read_text())
    pid, notes = next((k, v) for k, v in d["places"].items() if any(n["kind"] == "zone" for n in v))
    r = client.get(f"/api/v1/places/{pid}/notices").json()
    zone = next(n for n in r if n["kind"] == "zone")
    assert zone["zone_items"] and zone["source_url"].startswith("https://www.data.go.kr/")
    assert all("가능" not in n["title"] for n in r)
    assert client.get("/api/v1/places/999999/notices").json() == []
