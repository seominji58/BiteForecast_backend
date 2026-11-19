"""낚시터 ↔ 카카오 로컬 장소 매칭 → 도로명 주소·카카오 장소 링크, 위치 보정 (2026-11-19, 사용자 승인).

- 배 낚시·섬/해역 지점(boat, point)을 뺀 낚시터를 이름으로 카카오 키워드 검색 (좌표가 믿을 만하면 반경 20km)
- 붙이는 기준 (보수적): 이름 유사 0.8 이상 + 같은 시군구 + 현재 위치에서 3km 안
  + 업종이 낚시·항구이거나, 이름이 똑같은 공원·체험마을 (식당·카페 등 엉뚱한 곳 제외)
- 300m 이상 떨어진 곳은 좌표를 카카오 위치로 바꾼다 (seeds/places.json). 좌표 등급은 올리지 않는다
  (카카오 위치도 업체가 등록한 위치라 실제 낚시 자리를 보증하지 않음)
- 결과: seeds/kakao_places.json (서버가 /places/{id}/kakao 로 준다)

실행 (backend 폴더, .env 의 KAKAO_REST_KEY 필요):
  python -m scripts.match_kakao_places            # 미리보기
  python -m scripts.match_kakao_places --write    # kakao_places.json 저장 + places.json 좌표 보정
"""

import json
import sys
import time
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path

import httpx

from app.core.config import get_settings
from scripts.match_tour_photos import PLACES_API, km, norm

SEEDS = Path(__file__).resolve().parent.parent / "seeds"
OUT = SEEDS / "kakao_places.json"
URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
MOVE_M = 300  # 이보다 멀면 좌표 보정
MAX_KM = 3


def search(p: dict, key: str) -> list[dict]:
    params = {"query": p["name"], "size": 15}
    if p.get("lat") and p.get("lon") and not p.get("location_suspect"):
        params |= {"x": p["lon"], "y": p["lat"], "radius": 20000, "sort": "accuracy"}
    for attempt in range(3):
        try:
            r = httpx.get(URL, params=params, headers={"Authorization": f"KakaoAK {key}"}, timeout=15)
            r.raise_for_status()
            return r.json().get("documents", [])
        except (httpx.HTTPError, ValueError):
            time.sleep(1 + attempt)
    return []


def ok_category(cat: str, sim: float) -> bool:
    if "낚시" in cat or "항구" in cat:
        return True
    return sim == 1.0 and ("공원" in cat or "체험마을" in cat)


def best_match(p: dict, docs: list[dict]) -> dict | None:
    sigungu = p["region_name"].split()[1] if len(p["region_name"].split()) > 1 else ""
    best = None
    for d in docs:
        sim = SequenceMatcher(None, norm(p["name"]), norm(d["place_name"])).ratio()
        if best is None or sim > best[0]:
            best = (sim, d)
    if not best:
        return None
    sim, d = best
    dist = km(p["lat"], p["lon"], float(d["y"]), float(d["x"])) if p.get("lat") and p.get("lon") else None
    if sim < 0.8 or sigungu not in d["address_name"] or dist is None or dist > MAX_KM:
        return None
    if not ok_category(d["category_name"], sim):
        return None
    return {
        "name": d["place_name"],
        "url": d["place_url"].replace("http://", "https://"),
        "road_address": d["road_address_name"] or d["address_name"],
        "category": d["category_name"].split(">")[-1].strip(),
        "phone": d.get("phone") or None,
        "lat": round(float(d["y"]), 6),
        "lon": round(float(d["x"]), 6),
        "move_m": round(dist * 1000),
        "name_sim": round(sim, 2),
    }


def main() -> None:
    write = "--write" in sys.argv
    key = get_settings().kakao_rest_key
    if not key:
        sys.exit("KAKAO_REST_KEY 없음")
    places = [p for p in httpx.get(PLACES_API, timeout=30).json() if p["type"] not in ("boat", "point")]
    matches: dict[str, dict] = {}
    for p in places:
        m = best_match(p, search(p, key))
        if m:
            m["moved"] = m["move_m"] >= MOVE_M
            matches[str(p["id"])] = m | {"_place": p}
            flag = "좌표 보정" if m["moved"] else "링크만"
            print(f"  ✓ {p['id']:>4} {p['name']} ↔ {m['name']} ({m['move_m']}m, {m['category']}) {flag}")
        time.sleep(0.05)
    moved = [m for m in matches.values() if m["moved"]]
    print(f"검색 {len(places)}곳 · 매칭 {len(matches)}곳 (좌표 보정 {len(moved)}곳)")
    if not write:
        print("(미리보기) 저장하려면 --write")
        return

    path = SEEDS / "places.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    idx = {(r["name"], q["name"]): q for r in data["regions"] for q in r["places"]}
    fixed = 0
    for m in moved:
        p = m["_place"]
        q = idx.get((p["region_name"], p["name"]))
        if q is None:
            print(f"  ! places.json 에 없음: {p['region_name']} {p['name']}")
            continue
        q["lat"], q["lon"] = m["lat"], m["lon"]
        q.setdefault("info", {})["coord_source"] = f"카카오 로컬 장소 「{m['name']}」 위치 (2026-11-19 보정)"
        fixed += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for m in matches.values():
        m.pop("_place")
    OUT.write_text(
        json.dumps(
            {
                "_note": "카카오 로컬 키워드 검색 매칭. "
                "scripts/match_kakao_places.py 로 생성 — 직접 고치지 말 것",
                "source": "카카오",
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "places": matches,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"저장: {OUT} ({len(matches)}곳) · places.json 좌표 보정 {fixed}곳")


if __name__ == "__main__":
    main()
