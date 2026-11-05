"""seeds/places.json 생성 (지원 장소 목록).

출처
1. 전국낚시터정보표준데이터 (지자체 신고 낚시터, 공공데이터포털)
   낚시터유형 「바다」 중 좌표가 있는 곳 → 유료 낚시터(paid)
2. 국립해양조사원 바다낚시지수 지점 (seeds/fishing_points.json)
   해상 거리 표기(예: 「…(27km)」)가 있으면 선상(boat), 아니면 포인트(point)
   지역명은 OpenStreetMap Nominatim 역지오코딩으로 붙인다 (초당 1회 이하)
   결과는 seeds/fishing_points_regions.json 에 캐시
3. 기존 수동 지정 장소 (속초·보령·부산 8곳)

사용: python scripts/build_places.py <낚시터정보.csv>
"""

import csv
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

SEEDS = Path(__file__).resolve().parent.parent / "seeds"

SIDO_SHORT = {
    "서울특별시": "서울",
    "부산광역시": "부산",
    "대구광역시": "대구",
    "인천광역시": "인천",
    "광주광역시": "광주",
    "대전광역시": "대전",
    "울산광역시": "울산",
    "세종특별자치시": "세종",
    "경기도": "경기",
    "강원도": "강원",
    "강원특별자치도": "강원",
    "충청북도": "충북",
    "충청남도": "충남",
    "전라북도": "전북",
    "전북특별자치도": "전북",
    "전라남도": "전남",
    "전남광주통합특별시": "전남",
    "경상북도": "경북",
    "경상남도": "경남",
    "제주특별자치도": "제주",
}

MANUAL = [
    ("강원 속초시", "동명항", "wharf", 38.21036, 128.60124),
    ("강원 속초시", "대포항", "wharf", 38.17253, 128.6065),
    ("충남 보령시", "대천항", "wharf", 36.33036, 126.51045),
    ("충남 보령시", "무창포항", "wharf", 36.24887, 126.53709),
    ("충남 보령시", "오천항", "wharf", 36.43965, 126.51945),
    ("부산 해운대구", "미포", "wharf", 35.15808, 129.17293),
    ("부산 해운대구", "청사포", "wharf", 35.16126, 129.19138),
    ("부산 해운대구", "송정", "beach", 35.17765, 129.19858),
]


def region_from_address(addr: str) -> str | None:
    parts = addr.split()
    if len(parts) < 2:
        return None
    sido = SIDO_SHORT.get(parts[0])
    if not sido:
        return None
    sigungu = parts[1]
    # 세종처럼 시군구가 없는 경우
    if not re.search(r"(시|군|구)$", sigungu):
        return sido
    return f"{sido} {sigungu}"


def clean(v: str | None) -> str | None:
    v = (v or "").strip()
    return None if v in ("", "-", "없음") else v


def load_csv(path: Path) -> list[dict]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        if r["낚시터유형"] != "바다" or not r["WGS84위도"].strip() or not r["WGS84경도"].strip():
            continue
        addr = clean(r["소재지도로명주소"]) or clean(r["소재지지번주소"]) or ""
        region = region_from_address(addr) or region_from_address(r["소재지지번주소"] or "")
        if not region:
            print("  지역 판별 실패, 제외:", r["낚시터명"], addr)
            continue
        out.append(
            {
                "region": region,
                "name": r["낚시터명"].strip(),
                "type": "paid",
                "lat": round(float(r["WGS84위도"]), 6),
                "lon": round(float(r["WGS84경도"]), 6),
                "info": {
                    "source": "전국낚시터정보표준데이터",
                    "address": addr or None,
                    "phone": clean(r["낚시터전화번호"]),
                    "species": clean(r["주요어종"]),
                    "fee": clean(r["이용요금"]),
                    "facility": clean(r["수상시설물유형"]),
                    "manager": clean(r["관리기관명"]),
                    "data_date": clean(r["데이터기준일자"]),
                },
            }
        )
    return out


def reverse_region(lat: float, lon: float) -> str | None:
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
        {"lat": lat, "lon": lon, "format": "json", "zoom": 10, "accept-language": "ko"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "BiteForecast-dev/0.1 (student project)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    a = d.get("address") or {}
    sido_full = a.get("province") or a.get("state") or a.get("city")
    sido = SIDO_SHORT.get(sido_full or "", None)
    sigungu = a.get("county") or a.get("city") if a.get("province") or a.get("state") else a.get("borough")
    if not sido:
        return None
    if sigungu and sigungu != sido_full and re.search(r"(시|군|구)$", sigungu):
        return f"{sido} {sigungu}"
    return sido


def load_fishing_points() -> list[dict]:
    points = json.loads((SEEDS / "fishing_points.json").read_text(encoding="utf-8"))["points"]
    cache_path = SEEDS / "fishing_points_regions.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    out = []
    for p in points:
        offshore = re.search(r"\(\d+km\)$", p["name"]) is not None
        if p["name"] not in cache:
            try:
                cache[p["name"]] = reverse_region(p["lat"], p["lon"])
            except Exception as e:  # 네트워크 실패 시 다음 실행에서 재시도
                print("  역지오코딩 실패:", p["name"], e)
                cache[p["name"]] = None
            time.sleep(1.1)
        region = cache[p["name"]] or "해상"
        out.append(
            {
                "region": region,
                "name": p["name"],
                "type": "boat" if offshore else "point",
                "lat": p["lat"],
                "lon": p["lon"],
                "info": {"source": "국립해양조사원 바다낚시지수 지점"},
            }
        )
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main() -> None:
    csv_places = load_csv(Path(sys.argv[1]))
    fish_places = load_fishing_points()
    manual = [
        {
            "region": r,
            "name": n,
            "type": t,
            "lat": la,
            "lon": lo,
            "info": {"source": "수동 지정 (OpenStreetMap 좌표)"},
        }
        for r, n, t, la, lo in MANUAL
    ]

    seen: set[tuple[str, str]] = set()
    places = []
    for p in manual + fish_places + csv_places:
        key = (p["region"], p["name"])
        if key in seen:
            continue
        seen.add(key)
        places.append(p)

    by_region: dict[str, list] = defaultdict(list)
    for p in places:
        by_region[p["region"]].append({k: v for k, v in p.items() if k != "region"})
    out = {
        "_note": (
            "지원 장소. 출처: 전국낚시터정보표준데이터(바다·좌표 있음), "
            "국립해양조사원 바다낚시지수 지점, 수동 지정. "
            "좌표는 각 출처 값 그대로이며 정확한 낚시 지점을 보증하지 않는다. "
            "scripts/build_places.py 로 생성."
        ),
        "regions": [{"name": r, "places": ps} for r, ps in sorted(by_region.items())],
    }
    (SEEDS / "places.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    types = defaultdict(int)
    for p in places:
        types[p["type"]] += 1
    print(f"장소 {len(places)}곳, 지역 {len(by_region)}개, 유형 {dict(types)}")


if __name__ == "__main__":
    main()
