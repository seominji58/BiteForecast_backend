# ruff: noqa: E501  — 안내 문장은 문장 단위로 둔다
"""낚시터별 공공데이터 안내 만들기 (2026-11-26) → seeds/place_notices.json

판정이 아니라 「공식 자료 안내」만 만든다. 낚시 가능·불가로 표시하지 않는다.
- 국립공원 안: 국립공원공단 공원경계 SHP (data.go.kr 15017313, 2026-11-13 수정) — 점이 폴리곤 안
- 국가어항: 해양수산부 국가어항구역 (15149006) — 낚시터 좌표 0.3km 안에 구역이 있고 이름이 맞을 때
- 해변: 낚시터 종류가 해변이거나 이름에 해수욕장·해변 → 개장 기간 조례 제한 일반 안내 (날짜는 자료가 없어 넣지 않음)
- 시군 낚시통제구역: 시군이 공개한 CSV (좌표 없음) → 같은 시군 낚시터에 「이 시군 공고 목록」 (원문 그대로)

원본 파일은 data/public/ 에 둔다 (출처·기준일은 아래 SOURCES).
실행: pip install pyshp  (이 스크립트만 씀)
      python scripts/build_place_notices.py [--api https://biteforecast-api.fly.dev/api/v1]
"""

import argparse
import csv
import io
import json
import math
import re
from datetime import date
from pathlib import Path

import httpx
import shapefile  # pyshp

from app.core.utmk import to_utmk

ROOT = Path(__file__).resolve().parent.parent
PUB = ROOT / "data" / "public"
OUT = ROOT / "seeds" / "place_notices.json"

PARK_NAMES = {}  # NPK_CD → 이름 (파일에서 읽음)
SOURCES = {
    "park": {
        "name": "국립공원공단 국립공원 공원경계",
        "url": "https://www.data.go.kr/data/15017313/fileData.do",
        "date": "2026-11-13",
    },
    "harbor": {
        "name": "해양수산부 국가어항구역",
        "url": "https://www.data.go.kr/data/15149006/fileData.do",
        "date": "2025",
    },
}
# 시군 낚시통제구역 CSV: 파일 → (낚시터 지역 이름, 데이터 이름, 기준일)
ZONE_FILES = {
    "15160425": ("강원 강릉시", "강릉시 낚시금지 제한 통제구역 현황", "2026-07-20"),
    "15160437": ("강원 속초시", "속초시 낚시통제구역 현황", "2026-07-21"),
    "15160427": ("경남 고성군", "경상남도 고성군 낚시통제및금지구역", "2026-07-20"),
    "15116933": ("부산 수영구", "부산광역시 수영구 낚시통제구역지정현황", "2026-08-13"),
    "15160345": ("충남 당진시", "충청남도 당진시 낚시금지구역", "2026-07-14"),
    "15119776": ("부산 기장군", "부산광역시 기장군 낚시통제구역", "2026-11-23"),
}


def _km(a, b, c, d):
    p = math.radians
    x = math.sin(p(c - a) / 2) ** 2 + math.cos(p(a)) * math.cos(p(c)) * math.sin(p(d - b) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(x))


def _inside(x, y, ring):
    c = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _parks():
    r = shapefile.Reader(str(PUB / "park_15017313" / "park"), encoding="cp949")
    out = []
    for sr in r.shapeRecords():
        s = sr.shape
        idx = list(s.parts) + [len(s.points)]
        rings = [s.points[idx[i] : idx[i + 1]] for i in range(len(idx) - 1)]
        out.append((sr.record[1], rings))
    return out


def _harbors():
    rows = list(csv.DictReader(open(PUB / "national_harbor_15149006.csv", encoding="utf-8")))
    out = []
    for r in rows:
        pts = [
            tuple(map(float, p.split()[:2]))
            for ring in re.findall(r"\(\(([^()]+)\)", r["공간정보"])
            for p in ring.split(",")
        ]
        out.append((r["국가어항구역명"], pts))
    return out


def _decode(b: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", "replace")


def _pick(row: dict, *keys) -> str | None:
    for k in keys:
        for rk, v in row.items():
            if rk and rk.strip() == k and v and v.strip():
                return re.sub(r"\s+", " ", v.strip())
    return None


def _zones():
    out = {}
    for pk, (region, title, day) in ZONE_FILES.items():
        rows = list(csv.DictReader(io.StringIO(_decode((PUB / f"zone_{pk}.csv").read_bytes()))))
        items = []
        for r in rows:
            name = _pick(r, "명칭", "수계명", "지정범위(지역)")
            area = _pick(r, "주소", "지정범위(대상지역)", "지정범위", "위치(주소)")
            if name == area:
                area = None
            items.append(
                {
                    "name": name,
                    "area": area,
                    "since": _pick(r, "지정일", "지정일자", "지정일자(고시)", "시행일"),
                    "rule": _pick(r, "금지또는 제한되는 행위의 내용"),
                }
            )
        out[region] = {
            "source": title,
            "url": f"https://www.data.go.kr/data/{pk}/fileData.do",
            "date": day,
            "items": [i for i in items if i["name"]],
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="https://biteforecast-api.fly.dev/api/v1")
    a = ap.parse_args()
    places = httpx.get(f"{a.api}/places", timeout=30).json()
    parks, harbors, zones = _parks(), _harbors(), _zones()
    notes: dict[str, list] = {}
    for p in places:
        if p.get("lat") is None or p.get("location_suspect"):
            continue
        lat, lon, ns = p["lat"], p["lon"], []
        x, y = to_utmk(lat, lon)
        park = next((n for n, rings in parks if sum(_inside(x, y, rg) for rg in rings) % 2 == 1), None)
        if park:
            ns.append(
                {
                    "kind": "park",
                    "title": f"{park}국립공원 경계 안",
                    "detail": "국립공원공단 경계 자료상 공원 안이에요(경계는 도면을 옮긴 것이라 실제와 조금 다를 수 있어요). 국립공원은 갯바위 등 출입을 통제하는 경우가 있으니 출조 전 공원 공지를 확인하세요.",
                    "source": "park",
                }
            )
        hit = min(
            ((min(_km(lat, lon, py, px) for px, py in pts), n) for n, pts in harbors), default=(99, None)
        )
        if hit[0] <= 0.3:
            ns.append(
                {
                    "kind": "harbor",
                    "title": f"국가어항 {hit[1]}",
                    "detail": "해양수산부가 지정한 국가어항이에요. 배가 드나드는 곳·어항 시설에서는 낚시를 삼가 주세요.",
                    "source": "harbor",
                }
            )
        if p["type"] == "beach" or re.search("해수욕장|해변", p["name"]):
            ns.append(
                {
                    "kind": "beach",
                    "title": "해수욕장 개장 기간 주의",
                    "detail": "해수욕장 개장 기간(보통 여름철)에는 시군 조례로 낚시가 제한될 수 있어요.",
                    "source": None,
                }
            )
        if p["region_name"] in zones:
            z = zones[p["region_name"]]
            ns.append(
                {
                    "kind": "zone",
                    "title": f"{p['region_name']} 낚시통제구역 {len(z['items'])}곳",
                    "detail": "시군이 지정한 낚시통제구역 목록이에요. 이 낚시터가 들어 있는지는 위치를 직접 확인하세요.",
                    "source": "zone",
                    "region": p["region_name"],
                }
            )
        if ns:
            notes[str(p["id"])] = ns
    OUT.write_text(
        json.dumps(
            {
                "_note": "scripts/build_place_notices.py 로 생성 — 직접 고치지 말 것. 판정이 아닌 공식 자료 안내",
                "generated_at": date.today().isoformat(),
                "sources": SOURCES,
                "zones": zones,
                "places": notes,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    from collections import Counter

    print(len(notes), "곳", Counter(n["kind"] for v in notes.values() for n in v))


if __name__ == "__main__":
    main()
