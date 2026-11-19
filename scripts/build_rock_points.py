"""해양수산부 갯바위낚시포인트(2022-12-31) → 지도 「참고 포인트」 자료 (탐험 1단계, 2026-11-19).

- 입력: 06_개발환경/data_raw/해양수산부_공동활용체계_갯바위낚시포인트_20221231.csv
  (공공데이터포털 15148580, CP949)
- 좌표: 공간정보 POINT(EPSG:5179, UTM-K) → WGS84 경위도 (표준 라이브러리로 역변환, 원본 위도(도분초)와 대조)
- 해양경찰청 연안 출입통제구역 안이거나 200m 이내 → 뺀다 (공식 자료에 있어도 출입 금지일 수 있음)
- 연안사고 위험구역 안이거나 100m 이내 → 「위험구역」 경고를 붙인다 (빼지 않음)
- 낚시 허용 여부는 이 자료에 없다. 앱은 「참고 위치」로만 보여주고 추천·인증 대상으로 쓰지 않는다
- 결과: seeds/rock_points.json (서버가 /rock-points 로 준다)

실행 (backend 폴더):
  python -m scripts.build_rock_points            # 미리보기
  python -m scripts.build_rock_points --write    # 저장
"""

import csv
import io
import json
import math
import re
import sys
from pathlib import Path

from scripts.import_coastal_zones import RAW, SOURCES, _dbf, _dist_m, _inside, _members, _polygons

CSV = RAW / "해양수산부_공동활용체계_갯바위낚시포인트_20221231.csv"
OUT = Path(__file__).resolve().parent.parent / "seeds" / "rock_points.json"
CONTROL_M = 200
DANGER_M = 100


def utmk_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """EPSG:5179 → (위도, 경도). GRS80, 중앙자오선 127.5°, 원점 위도 38°, k0 0.9996, 가산 1e6 / 2e6"""
    a, f = 6378137.0, 1 / 298.257222101
    k0, lat0, lon0, fe, fn = 0.9996, math.radians(38), math.radians(127.5), 1_000_000.0, 2_000_000.0
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)

    def meridian(phi: float) -> float:
        return a * (
            (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * phi
            - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * math.sin(2 * phi)
            + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * math.sin(4 * phi)
            - (35 * e2**3 / 3072) * math.sin(6 * phi)
        )

    m = meridian(lat0) + (y - fn) / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )
    s, c, t = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    n1 = a / math.sqrt(1 - e2 * s * s)
    r1 = a * (1 - e2) / (1 - e2 * s * s) ** 1.5
    c1, t1 = ep2 * c * c, t * t
    d = (x - fe) / (n1 * k0)
    lat = phi1 - (n1 * t / r1) * (
        d * d / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d**6 / 720
    )
    lon = (
        lon0
        + (
            d
            - (1 + 2 * t1 + c1) * d**3 / 6
            + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d**5 / 120
        )
        / c
    )
    return math.degrees(lat), math.degrees(lon)


def dms(v: str) -> float | None:
    m = re.match(r"\s*(\d+)-(\d+)-([\d.]+)", v or "")
    return int(m[1]) + int(m[2]) / 60 + float(m[3]) / 3600 if m else None


def catches(text: str) -> list[dict]:
    """「▶감성돔 - 릴찌/ 장대 ▶농어 - 루어」 → [{species, methods}]"""
    out = []
    for part in re.split(r"▶", text or ""):
        if not part.strip():
            continue
        sp, _, how = part.partition("-")
        methods = [w.strip() for w in how.split("/") if w.strip()]
        if sp.strip():
            out.append({"species": sp.strip(), "methods": methods})
    return out


def zones(tag: str):
    src = SOURCES[tag]
    m = _members(RAW / src["zip"])
    return [(p, a) for p, a in zip(_polygons(m[".shp"]), _dbf(m[".dbf"], src["enc"]), strict=False) if p]


def nearest(lat: float, lon: float, polys) -> tuple[float, list[str]] | None:
    best = None
    for poly, a in polys:
        d = 0.0 if _inside(lon, lat, poly) else _dist_m(lon, lat, poly)
        if best is None or d < best[0]:
            best = (d, a)
    return best


def main() -> None:
    write = "--write" in sys.argv
    rows = list(csv.DictReader(io.StringIO(CSV.read_bytes().decode("cp949"))))
    control, danger = zones("control"), zones("danger")
    points, dropped, diffs = [], [], []
    for r in rows:
        mm = re.match(r"POINT \(([\d.]+) ([\d.]+)\)", r["공간정보"])
        if not mm:
            continue
        lat, lon = utmk_to_wgs84(float(mm[1]), float(mm[2]))
        ref = dms(r["갯바위낚시포인트도분초위도"])
        if ref is not None:
            diffs.append(abs(ref - lat) * 111_000)
        c = nearest(lat, lon, control)
        if c and c[0] <= CONTROL_M:
            dropped.append((r["포인트명"], r["행정구역명"], c[1][2], round(c[0])))
            continue
        dz = nearest(lat, lon, danger)
        warn = None
        if dz and dz[0] <= DANGER_M:
            a = dz[1]
            warn = f"{a[4]} ({a[5]}) · {'안' if dz[0] == 0 else f'{round(dz[0])}m 근처'}"
        points.append(
            {
                "id": int(r["공간정보일련번호"]),
                "name": r["포인트명"].strip(),
                "area": r["포인트지역명"].strip(),
                "admin": r["행정구역명"].strip(),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "depth": r["수심범위내용"].strip() or None,
                "bottom": r["주원료내용"].strip() or None,
                "tide": r["조수물때내용"].strip() or None,
                "catches": catches(r["낚시방법대상내용"]),
                "danger": warn,
            }
        )
    print(
        f"원본 {len(rows)}곳 → 참고 포인트 {len(points)}곳 "
        f"(출입통제구역 {CONTROL_M}m 안 제외 {len(dropped)}곳)"
    )
    diffs.sort()
    print(
        f"좌표 변환 검산: 원본 위도(도분초)와 차이 중앙값 {diffs[len(diffs) // 2]:.1f}m"
        f" · 95% {diffs[int(len(diffs) * 0.95)]:.1f}m"
        f" · 1km 넘는 곳 {sum(1 for d in diffs if d > 1000)}곳(원본 위도 칸 오기 — 공간정보 좌표를 쓴다)"
    )
    print(f"연안사고 위험구역 {DANGER_M}m 안: {sum(1 for p in points if p['danger'])}곳 (경고 표시)")
    for d in dropped:
        print("  제외:", d)
    if not write:
        print("(미리보기) 저장하려면 --write")
        return
    OUT.write_text(
        json.dumps(
            {
                "_note": "scripts/build_rock_points.py 로 생성 — 직접 고치지 말 것",
                "source": "해양수산부 갯바위낚시포인트 (2022-12-31, 공공데이터포털 15148580)",
                "excluded": f"해양경찰청 연안 출입통제구역(2023-05-01) {CONTROL_M}m 안 {len(dropped)}곳 제외",
                "notice": "낚시 허용 여부·접근 가능 여부는 확인되지 않은 참고 위치",
                "points": points,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"저장: {OUT} ({OUT.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    main()
