"""한국관광공사 TourAPI 바다낚시 장소를 낚시터로 추가 (2026-11-19, 사용자 승인 18곳).

- 우리 데이터에 없는 관광공사 바다낚시 장소 중 사용자가 고른 18곳을 seeds/places.json 에 덧붙인다
  (기존 장소는 건드리지 않는다. 같은 지역·같은 이름이 이미 있으면 건너뜀)
- 종류: 낚시터·낚시공원 → 유료 낚시터(paid), 배낚시·항구 낚시 → 항구(wharf)
- 좌표·주소·전화는 관광공사 등록값 그대로 (실제 낚시 자리 확인 전)
- 적재는 기존 방식: python -m seeds.load (places.json 기준으로 장소·관측소 연결)
- 사진은 다음에 scripts/match_tour_photos.py --write 로 다시 매칭하면 붙는다

실행 (backend 폴더):
  python -m scripts.add_tour_places            # 미리보기
  python -m scripts.add_tour_places --write    # seeds/places.json 에 반영
"""

import json
import sys
from pathlib import Path

from scripts.build_places import region_from_address
from scripts.match_tour_photos import fishing_items

SEEDS = Path(__file__).resolve().parent.parent / "seeds"
SOURCE = "한국관광공사 관광정보(TourAPI)"

# 사용자 승인 목록 (2026-11-19): 관광공사 이름 → 종류
APPROVED: dict[str, str] = {
    "선재낚시공원": "paid",
    "영흥바다낚시터": "paid",
    "용담바다낚시터": "paid",
    "소래바다낚시터": "paid",
    "갈매기배낚시": "wharf",
    "인천락실내바다낚시터": "paid",
    "드림바다실내낚시터": "paid",
    "선두바다낚시터": "paid",
    "강화도 황청낚시터": "paid",
    "동검레저바다낚시": "paid",
    "황산초지바다낚시터": "paid",
    "수산항 낚시터": "wharf",
    "인구항 배낚시": "wharf",
    "지세포 낚시공원": "paid",
    "장포리 바다낚시": "paid",
    "득량만바다낚시공원": "paid",
    "안면도 라암도 해상낚시공원": "paid",
    "차귀도 바다낚시": "wharf",
}


def main() -> None:
    write = "--write" in sys.argv
    path = SEEDS / "places.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    by_title = {t["title"].strip(): t for t in fishing_items()}
    missing = [n for n in APPROVED if n not in by_title]
    if missing:
        sys.exit(f"관광공사 목록에서 찾지 못함: {missing}")

    regions = {r["name"]: r for r in data["regions"]}
    added, skipped = [], []
    for name, ptype in APPROVED.items():
        t = by_title[name]
        region = region_from_address(t.get("addr1") or "")
        if not region:
            sys.exit(f"지역을 정하지 못함: {name} ({t.get('addr1')})")
        reg = regions.get(region)
        if reg is None:
            reg = {"name": region, "places": []}
            data["regions"].append(reg)
            regions[region] = reg
        if any(p["name"] == name for p in reg["places"]):
            skipped.append(name)
            continue
        reg["places"].append(
            {
                "name": name,
                "type": ptype,
                "lat": round(float(t["mapy"]), 6),
                "lon": round(float(t["mapx"]), 6),
                "info": {
                    "source": SOURCE,
                    "address": " ".join(filter(None, [t.get("addr1"), t.get("addr2")])).strip() or None,
                    "phone": (t.get("tel") or "").strip() or None,
                    "data_date": (t.get("modifiedtime") or "")[:8] or None,
                },
            }
        )
        added.append((region, name, ptype, t.get("addr1")))

    for r, n, ptype, a in added:
        print(f"  + {r} · {n} ({'유료 낚시터' if ptype == 'paid' else '항구'}) — {a}")
    print(f"추가 {len(added)}곳, 이미 있음 {len(skipped)}곳 {skipped or ''}")
    total = sum(len(r["places"]) for r in data["regions"])
    print(f"places.json 장소 수: {total}")
    if not write:
        print("(미리보기) 반영하려면 --write")
        return
    data["regions"].sort(key=lambda r: r["name"])
    if SOURCE not in data.get("_note", ""):
        data["_note"] = data.get("_note", "") + f" + {SOURCE} 바다낚시 장소(2026-11-19 승인 18곳, scripts/add_tour_places.py)."
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
