"""Google Places(New) 사진 시험 — 낚시터 N곳을 이름으로 찾아 사진이 몇 곳에 있는지 센다 (DB·파일 안 바꿈).

- Text Search (New): 이름 + 시군구로 검색, 우리 좌표 반경 3km 안으로 제한
- 붙는 기준: 이름 유사 0.7 이상 + 3km 안 (관광공사·카카오 매칭과 같은 보수적 기준)
- 사진은 개수와 작성자 표시(authorAttributions)만 본다. 사진 파일은 받지 않는다 (요금·정책 확인 전)

실행 (backend 폴더, .env 의 GOOGLE_PLACES_API_KEY 필요):
  python -m scripts.try_google_places          # 사진 없는 곳 20곳
  python -m scripts.try_google_places 50       # 50곳
"""

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

import httpx

from app.core.config import get_settings
from scripts.match_tour_photos import PLACES_API, km, norm

SEARCH = "https://places.googleapis.com/v1/places:searchText"
FIELDS = "places.id,places.displayName,places.location,places.photos,places.googleMapsUri"
SEEDS = Path(__file__).resolve().parent.parent / "seeds"


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    key = get_settings().google_places_api_key
    if not key:
        sys.exit("GOOGLE_PLACES_API_KEY 없음 (.env)")
    have = set(json.loads((SEEDS / "tour_photos.json").read_text(encoding="utf-8"))["places"])
    places = [
        p
        for p in httpx.get(PLACES_API, timeout=30).json()
        if p["type"] not in ("boat", "point") and p.get("lat") and str(p["id"]) not in have
    ][:n]
    found = with_photo = 0
    for p in places:
        body = {
            "textQuery": f"{p['name']} {p['region_name']}",
            "languageCode": "ko",
            "regionCode": "KR",
            "pageSize": 5,
            "locationBias": {"circle": {"center": {"latitude": p["lat"], "longitude": p["lon"]}, "radius": 3000}},
        }
        r = httpx.post(SEARCH, json=body, headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS}, timeout=20)
        if r.status_code != 200:
            sys.exit(f"구글 오류 {r.status_code}: {r.text[:300]}")
        best = None
        for g in r.json().get("places", []):
            name = g.get("displayName", {}).get("text", "")
            loc = g.get("location", {})
            d = km(p["lat"], p["lon"], loc.get("latitude", 0), loc.get("longitude", 0))
            sim = SequenceMatcher(None, norm(p["name"]), norm(name)).ratio()
            if d <= 3 and sim >= 0.7 and (best is None or sim > best[0]):
                best = (sim, d, name, g)
        if not best:
            print(f"  ✗ {p['id']:>4} {p['name']} — 못 찾음")
            continue
        found += 1
        photos = best[3].get("photos", [])
        with_photo += bool(photos)
        who = {a.get("displayName") for ph in photos for a in ph.get("authorAttributions", [])}
        print(
            f"  {'✓' if photos else '·'} {p['id']:>4} {p['name']} ↔ {best[2]} ({round(best[1] * 1000)}m) "
            f"사진 {len(photos)}장 {sorted(who)[:3]}"
        )
    print(f"\n{len(places)}곳 중 구글에서 찾음 {found}곳 · 사진 있음 {with_photo}곳")


if __name__ == "__main__":
    main()
