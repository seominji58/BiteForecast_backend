"""UTM-K (EPSG:5179, GRS80 횡메르카토르) ↔ WGS84 위경도 변환.

행정안전부 좌표제공 API(entX·entY)가 UTM-K 좌표를 돌려주므로 위경도로 바꿔 거리를 비교한다.
투영 상수: 원점 위도 38°, 중앙 경선 127.5°, 축척 0.9996, 가산값 X 1,000,000 · Y 2,000,000 (EPSG:5179).
GRS80 과 WGS84 타원체 차이는 mm 수준이라 무시한다.
"""

import math

A = 6378137.0
F = 1 / 298.257222101
E2 = F * (2 - F)
EP2 = E2 / (1 - E2)
K0 = 0.9996
LAT0 = math.radians(38.0)
LON0 = math.radians(127.5)
FE, FN = 1_000_000.0, 2_000_000.0


def _m(phi: float) -> float:
    e4, e6 = E2 * E2, E2 * E2 * E2
    return A * (
        (1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
        - (35 * e6 / 3072) * math.sin(6 * phi)
    )


def to_utmk(lat: float, lon: float) -> tuple[float, float]:
    """(위도, 경도) → (x, y)"""
    phi, lam = math.radians(lat), math.radians(lon)
    n = A / math.sqrt(1 - E2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = EP2 * math.cos(phi) ** 2
    a = (lam - LON0) * math.cos(phi)
    x = FE + K0 * n * (a + (1 - t + c) * a**3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * EP2) * a**5 / 120)
    y = FN + K0 * (
        _m(phi)
        - _m(LAT0)
        + n
        * math.tan(phi)
        * (
            a * a / 2
            + (5 - t + 9 * c + 4 * c * c) * a**4 / 24
            + (61 - 58 * t + t * t + 600 * c - 330 * EP2) * a**6 / 720
        )
    )
    return x, y


def to_wgs84(x: float, y: float) -> tuple[float, float]:
    """(x, y) → (위도, 경도)"""
    e4, e6 = E2 * E2, E2 * E2 * E2
    m = _m(LAT0) + (y - FN) / K0
    mu = m / (A * (1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256))
    e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )
    c1 = EP2 * math.cos(phi1) ** 2
    t1 = math.tan(phi1) ** 2
    n1 = A / math.sqrt(1 - E2 * math.sin(phi1) ** 2)
    r1 = A * (1 - E2) / (1 - E2 * math.sin(phi1) ** 2) ** 1.5
    d = (x - FE) / (n1 * K0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d * d / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * d**6 / 720
    )
    lon = LON0 + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * d**5 / 120
    ) / math.cos(phi1)
    return math.degrees(lat), math.degrees(lon)
