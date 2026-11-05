"""기상청 단기예보 격자 변환 (위경도 → nx, ny). 기상청 동네예보 LCC 투영 표준 상수."""

from math import cos, log, pi, sin, tan

RE = 6371.00877  # 지구 반경 (km)
GRID = 5.0  # 격자 간격 (km)
SLAT1, SLAT2 = 30.0, 60.0  # 표준 위도
OLON, OLAT = 126.0, 38.0  # 기준점 경도·위도
XO, YO = 43, 136  # 기준점 격자 좌표

_DEG = pi / 180.0


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    re = RE / GRID
    slat1, slat2, olon, olat = SLAT1 * _DEG, SLAT2 * _DEG, OLON * _DEG, OLAT * _DEG
    sn = log(cos(slat1) / cos(slat2)) / log(tan(pi * 0.25 + slat2 * 0.5) / tan(pi * 0.25 + slat1 * 0.5))
    sf = tan(pi * 0.25 + slat1 * 0.5) ** sn * cos(slat1) / sn
    ro = re * sf / tan(pi * 0.25 + olat * 0.5) ** sn

    ra = re * sf / tan(pi * 0.25 + lat * _DEG * 0.5) ** sn
    theta = lon * _DEG - olon
    if theta > pi:
        theta -= 2.0 * pi
    if theta < -pi:
        theta += 2.0 * pi
    theta *= sn
    nx = int(ra * sin(theta) + XO + 0.5)
    ny = int(ro - ra * cos(theta) + YO + 0.5)
    return nx, ny


def grid_to_latlon(nx: int, ny: int) -> tuple[float, float]:
    """격자 중심의 위경도 (latlon_to_grid 의 역변환). 장소↔예보 격자 거리 계산용"""
    from math import atan, atan2, sqrt

    re = RE / GRID
    slat1, slat2, olon, olat = SLAT1 * _DEG, SLAT2 * _DEG, OLON * _DEG, OLAT * _DEG
    sn = log(cos(slat1) / cos(slat2)) / log(tan(pi * 0.25 + slat2 * 0.5) / tan(pi * 0.25 + slat1 * 0.5))
    sf = tan(pi * 0.25 + slat1 * 0.5) ** sn * cos(slat1) / sn
    ro = re * sf / tan(pi * 0.25 + olat * 0.5) ** sn

    xn = nx - XO
    yn = ro - ny + YO
    ra = sqrt(xn * xn + yn * yn)
    if sn < 0:
        ra = -ra
    alat = 2.0 * atan((re * sf / ra) ** (1.0 / sn)) - pi * 0.5
    if abs(xn) <= 0.0:
        theta = 0.0
    elif abs(yn) <= 0.0:
        theta = pi * 0.5 if xn > 0 else -pi * 0.5
    else:
        theta = atan2(xn, yn)
    alon = theta / sn + olon
    return alat / _DEG, alon / _DEG
