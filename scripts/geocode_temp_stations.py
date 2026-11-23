"""수온 관측소(국립수산과학원 실시간 관측) 이름 → 대략 좌표 → seeds/sea_temp_recent.json (2026-11-23).

원자료에 좌표가 없어 관측소 이름(예: 「강진 마량(fgmk6)」)을 카카오 키워드 검색으로 찾는다.
- 해안 분류(항구·섬·해수욕장·지명·어촌·방파제)를 먼저 고른다
- 검증: 이름 앞 지역명(강진·고흥…)이 주소에 있어야 하고, 우리 낚시터·갯바위 포인트 15km 안이어야 한다
  → 통과 못 한 관측소는 뺀다 (서울 카페로 잡힌 「고리」 등)
- 좌표는 「관측소 이름이 가리키는 동네」 수준이다. 가장 가까운 관측소를 고르는 데만 쓴다

입력: 06_개발환경/data_raw/nifs_실시간수온/monthly_by_station.json (scripts/build_recent_sea_temp.py)
실행: .venv/bin/python -m scripts.geocode_temp_stations
"""

import json
import math
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.core.config import get_settings

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT.parent / "06_개발환경" / "data_raw" / "nifs_실시간수온" / "monthly_by_station.json"
OUT = ROOT / "seeds" / "sea_temp_recent.json"
API = "https://biteforecast-api.fly.dev/api/v1/places"
COAST = ("항구", "섬", "해수욕장", "지명", "어촌", "방파제")
MAX_KM = 15


def km(a, b, c, d):
    p = math.radians
    h = math.sin(p(c - a) / 2) ** 2 + math.cos(p(a)) * math.cos(p(c)) * math.sin(p(d - b) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def main() -> None:
    key = get_settings().kakao_rest_key
    http = httpx.Client(headers={"Authorization": f"KakaoAK {key}"}, timeout=10)
    coast = [(p["lat"], p["lon"]) for p in httpx.get(API, timeout=30).json() if p.get("lat")]
    rocks = json.loads((ROOT / "seeds" / "rock_points.json").read_text(encoding="utf-8"))["points"]
    coast += [(r["lat"], r["lon"]) for r in rocks]
    out, dropped = [], []
    for s in json.loads(SRC.read_text(encoding="utf-8")):
        if len(s["monthly"]) < 12:
            continue
        name = re.sub(r"\(.*?\)", "", s["station"]).strip()
        words = name.split()
        hit = None
        for q in [name, words[-1]] if len(words) > 1 else [name]:
            docs = (
                http.get(
                    "https://dapi.kakao.com/v2/local/search/keyword.json", params={"query": q, "size": 5}
                )
                .json()
                .get("documents", [])
            )
            docs.sort(key=lambda d: 0 if any(w in d.get("category_name", "") for w in COAST) else 1)
            if docs:
                hit = docs[0]
                break
            time.sleep(0.05)
        if not hit:
            dropped.append(s["station"])
            continue
        lat, lon = float(hit["y"]), float(hit["x"])
        region_ok = (
            len(words) == 1 or words[0] in hit.get("address_name", "") or words[0] in hit["place_name"]
        )
        near = min(km(lat, lon, a, b) for a, b in coast)
        if not region_ok or near > MAX_KM:
            dropped.append(s["station"])
            continue
        out.append(
            {
                "station": s["station"],
                "sea": s["sea"],
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "located_by": hit["place_name"],
                "monthly": s["monthly"],
                "years": s["years"],
            }
        )
    OUT.write_text(
        json.dumps(
            {
                "_note": "scripts/build_recent_sea_temp.py + scripts/geocode_temp_stations.py 로 생성",
                "source": "국립수산과학원 실시간 해양수산환경 관측시스템 과거자료 (표층 수온, 1시간)",
                "period": "2019~2025",
                "method": "관측소별 연-월 평균(240시간 이상)의 평균, 3개 연도 이상인 달만, "
                "12개월 다 있는 관측소만",
                "location": "관측소 이름을 카카오 검색으로 찾은 대략 위치 (가장 가까운 관측소 고르기용)",
                "generated_at": datetime.now(UTC).date().isoformat(),
                "stations": out,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"관측소 {len(out)}곳 · 뺀 곳 {len(dropped)}: {dropped}")


if __name__ == "__main__":
    main()
