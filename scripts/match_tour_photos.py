"""낚시터 ↔ 한국관광공사 TourAPI(국문 관광정보, KorService2) 낚시 장소 매칭 → 실제 사진 (2026-11-18).

- 관광공사 「레포츠 > 수상 레포츠 > 바다낚시(A03030600)·민물낚시(A03030500)」
  + 「낚시」 키워드 레포츠를 모은다
- 우리 낚시터(좌표 있는 곳)마다 가까운 관광공사 낚시 장소를 찾아, 거리와 이름이 함께 맞을 때만 붙인다
  (엉뚱한 사진을 붙이지 않게 보수적으로: 0.5km 안 + 이름 유사 0.45 이상, 또는 2km 안 + 이름 유사 0.7 이상)
- 사진은 관광공사 이미지 주소를 그대로 쓴다 (공공누리 제3유형: 출처 표시 · 변경 금지 → 앱은 원본 비율로 표시)
- 관광 정보에 없는 곳은 「관광사진 갤러리」(PhotoGalleryService1)에서
  이름이 똑같고 촬영 지역(시군)이 같은 사진만 덧붙인다 (항구·섬 풍경. 낚시 자리 사진은 아님)
- 결과: seeds/tour_photos.json (서버가 읽어서 /place-photos·/places/{id}/photos 로 준다). 다시 돌리면 덮어쓴다

실행 (backend 폴더, .env 의 DATA_GO_KR_API_KEY 필요):
  python -m scripts.match_tour_photos            # 매칭 미리보기만 (파일 안 씀)
  python -m scripts.match_tour_photos --write    # seeds/tour_photos.json 저장
"""

import json
import math
import re
import sys
import time
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path

import httpx

from app.core.config import get_settings

BASE = "https://apis.data.go.kr/B551011/KorService2"
OUT = Path(__file__).resolve().parent.parent / "seeds" / "tour_photos.json"
PLACES_API = "https://biteforecast-api.fly.dev/api/v1/places"
FISHING_CAT3 = ("A03030600", "A03030500")  # 바다낚시 · 민물낚시


def call(op: str, **params) -> list[dict]:
    key = get_settings().data_go_kr_api_key
    q = {"serviceKey": key, "MobileOS": "ETC", "MobileApp": "BiteForecast", "_type": "json", **params}
    for attempt in range(3):
        try:
            r = httpx.get(f"{BASE}/{op}", params=q, timeout=20)
            r.raise_for_status()
            body = r.json()["response"]["body"]
            items = body.get("items") or {}
            return items.get("item", []) if isinstance(items, dict) else []
        except (httpx.HTTPError, ValueError, KeyError):
            time.sleep(1 + attempt)
    return []


def https(url: str | None) -> str | None:
    if not url:
        return None
    return re.sub(r"^http://", "https://", url)


def norm(name: str) -> str:
    n = re.sub(r"\(.*?\)|\[.*?\]", "", name)
    n = re.sub(r"\s+", "", n)
    for w in (
        "바다낚시터",
        "해상낚시터",
        "낚시공원",
        "유료낚시터",
        "낚시터",
        "바다낚시",
        "낚시",
        "레저타운",
        "해상",
        "펜션",
    ):
        n = n.replace(w, "")
    return n


def km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def fishing_items() -> list[dict]:
    seen: dict[str, dict] = {}
    for cat3 in FISHING_CAT3:
        for it in call(
            "areaBasedList2", contentTypeId=28, cat1="A03", cat2="A0303", cat3=cat3, numOfRows=1000
        ):
            seen[it["contentid"]] = it
    for it in call("searchKeyword2", keyword="낚시", contentTypeId=28, numOfRows=1000):
        seen.setdefault(it["contentid"], it)
    return [it for it in seen.values() if it.get("mapx") and it.get("mapy")]


def alive(url: str | None) -> bool:
    """실제로 열리는 이미지인지 (관광공사 썸네일 주소 일부는 404)"""
    if not url:
        return False
    try:
        with httpx.stream("GET", url, timeout=20) as r:
            return r.status_code == 200 and r.headers.get("content-type", "").startswith("image")
    except httpx.HTTPError:
        return False


def images(it: dict) -> list[dict]:
    cands = []
    if it.get("firstimage"):
        cands.append((https(it["firstimage"]), https(it.get("firstimage2"))))
    for d in call("detailImage2", contentId=it["contentid"], imageYN="Y", numOfRows=10):
        cands.append((https(d.get("originimgurl")), https(d.get("smallimageurl"))))
    out: list[dict] = []
    for url, thumb in cands:
        if not url or any(x["url"] == url for x in out) or not alive(url):
            continue
        out.append({"url": url, "thumb": thumb if alive(thumb) else url})
        if len(out) >= 6:
            break
    return out


GALLERY = "https://apis.data.go.kr/B551011/PhotoGalleryService1/gallerySearchList1"


def gallery(p: dict) -> dict | None:
    """관광사진 갤러리: 제목이 낚시터 이름과 똑같고, 촬영 지역에 시군 이름이 들어 있는 사진만"""
    key = get_settings().data_go_kr_api_key
    q = {"serviceKey": key, "MobileOS": "ETC", "MobileApp": "BiteForecast", "_type": "json"}
    try:
        r = httpx.get(GALLERY, params=q | {"keyword": p["name"], "numOfRows": 30}, timeout=20)
        items = (r.json()["response"]["body"].get("items") or {}).get("item", [])
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    if isinstance(items, dict):
        items = [items]
    parts = p["region_name"].split()
    town = re.sub(r"[시군구]$", "", parts[1]) if len(parts) > 1 else parts[0]
    same = [
        it
        for it in items
        if it.get("galTitle", "").replace(" ", "") == p["name"].replace(" ", "")
        and town in (it.get("galPhotographyLocation") or "")
        and it.get("galWebImageUrl")
    ]
    if not same:
        return None
    who = same[0].get("galPhotographer") or "한국관광공사"
    same = [
        it for it in same if (it.get("galPhotographer") or "한국관광공사") == who
    ]  # 출처를 사진마다 정확히
    imgs = []
    for it in same:
        url = https(it["galWebImageUrl"])
        if url and all(x["url"] != url for x in imgs) and alive(url):
            imgs.append({"url": url, "thumb": url})
        if len(imgs) >= 6:
            break
    if not imgs:
        return None
    return {
        "contentid": same[0].get("galContentId"),
        "title": p["name"],
        "kind": "gallery",
        "license": f"관광사진 갤러리 · 촬영 {who} (출처 표시)",
        "images": imgs,
    }


def main() -> None:
    write = "--write" in sys.argv
    places = [p for p in httpx.get(PLACES_API, timeout=30).json() if p.get("lat") and p.get("lon")]
    tour = fishing_items()
    print(
        f"우리 낚시터 {len(places)}곳 · 관광공사 낚시 장소 {len(tour)}곳 "
        f"(사진 있는 곳 {sum(1 for t in tour if t.get('firstimage'))})"
    )
    matches: dict[str, dict] = {}
    near_misses = []
    for p in places:
        best = None
        for t in tour:
            d = km(p["lat"], p["lon"], float(t["mapy"]), float(t["mapx"]))
            if d > 2:
                continue
            sim = SequenceMatcher(None, norm(p["name"]), norm(t["title"])).ratio()
            ok = (d <= 0.5 and sim >= 0.45) or (d <= 2 and sim >= 0.7)
            cand = (ok, sim - d / 4, d, sim, t)
            if best is None or cand[:2] > best[:2]:
                best = cand
        if best and best[0] and best[4].get("firstimage"):
            _, _, d, sim, t = best
            matches[str(p["id"])] = {
                "contentid": t["contentid"],
                "title": t["title"],
                "dist_m": round(d * 1000),
                "name_sim": round(sim, 2),
                "license": "공공누리 제3유형 (출처 표시·변경 금지)"
                if t.get("cpyrhtDivCd") == "Type3"
                else t.get("cpyrhtDivCd"),
                "images": [],
                "_tour": t,
            }
            print(f"  ✓ {p['id']:>4} {p['name']} ↔ {t['title']} ({round(d * 1000)}m, 이름 {sim:.2f})")
        elif best and best[2] <= 2:
            near_misses.append((p, best))
    print(f"매칭 {len(matches)}곳")
    print("가깝지만 기준 미달(붙이지 않음):")
    for p, b in sorted(near_misses, key=lambda x: x[1][2])[:15]:
        print(
            f"  ✗ {p['name']} ↔ {b[4]['title']} ({round(b[2] * 1000)}m, 이름 {b[3]:.2f}, "
            f"사진 {'O' if b[4].get('firstimage') else 'X'})"
        )
    print("관광사진 갤러리 (이름·시군이 같은 사진만):")
    galleries: dict[str, dict] = {}
    for p in places:
        if str(p["id"]) in matches:
            continue
        g = gallery(p)
        if g:
            galleries[str(p["id"])] = g
            print(f"  ✓ {p['id']:>4} {p['name']} ({len(g['images'])}장, {g['license']})")
    print(f"갤러리 {len(galleries)}곳")
    if not write:
        print("\n(미리보기) 저장하려면 --write")
        return
    for m in matches.values():
        t = m.pop("_tour")
        m["images"] = images(t)
    matches.update(galleries)
    OUT.write_text(
        json.dumps(
            {
                "_note": "한국관광공사 TourAPI(KorService2) 낚시 장소 사진 매칭. "
                "scripts/match_tour_photos.py 로 생성 — 직접 고치지 말 것",
                "source": "한국관광공사",
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "places": matches,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"저장: {OUT} ({len(matches)}곳)")


if __name__ == "__main__":
    main()
