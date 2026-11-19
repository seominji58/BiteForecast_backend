"""참고 포인트(해수부 갯바위): 자료 파일 형식 · 출입통제 제외 · 좌표 변환"""

import math

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
