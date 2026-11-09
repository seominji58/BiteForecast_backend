"""UTM-K ↔ 위경도 변환 (행정안전부 좌표제공 API 대비)"""

from app.core.utmk import to_utmk, to_wgs84


def test_origin():
    x, y = to_utmk(38.0, 127.5)
    assert abs(x - 1_000_000) < 0.01 and abs(y - 2_000_000) < 0.01
    lat, lon = to_wgs84(1_000_000, 2_000_000)
    assert abs(lat - 38.0) < 1e-9 and abs(lon - 127.5) < 1e-9


def test_round_trip_korea_extremes():
    # 서산 삼길포 · 부산 · 제주 · 울릉도 — 왕복 오차 1cm 미만
    for lat, lon in [(37.0043, 126.4533), (35.2672, 129.0183), (33.25, 126.56), (37.48, 130.9)]:
        la, lo = to_wgs84(*to_utmk(lat, lon))
        assert abs(la - lat) < 1e-7 and abs(lo - lon) < 1e-7
