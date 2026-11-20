"""좌표 근처 주소 (카카오 좌표→주소) — 2026-11-20.

주소 칸이 없는 장소(지수 지점·선상 포인트 등)와 갯바위 참고 포인트 1,070곳에
「좌표가 속한 동·리」를 붙인다. 바위·바다 좌표는 번지 주소가 나오지 않으므로
- coord2address 에 결과가 있으면 그 주소(도로명 우선, 없으면 지번) → kind="address"
- 없으면 coord2regioncode 의 법정동(B) 이름 → kind="region" (앱에서 「○○리 근처」로 표시)
정확한 위치 주소가 아니라 「어느 동네인지」를 알려 주는 용도다.

실행 (카카오 REST 키 필요, 운영 장소 id 는 운영 API 에서 읽음):
  .venv/bin/python -m scripts.build_near_address
→ seeds/near_address.json
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.core.config import get_settings

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "seeds" / "near_address.json"
ROCK = ROOT / "seeds" / "rock_points.json"
API = "https://biteforecast-api.fly.dev/api/v1/places"
GEO = "https://dapi.kakao.com/v2/local/geo"


def lookup(http: httpx.Client, lat: float, lon: float) -> dict | None:
    q = {"x": lon, "y": lat}
    r = http.get(f"{GEO}/coord2address.json", params=q)
    r.raise_for_status()
    docs = r.json().get("documents", [])
    if docs:
        d = docs[0]
        road = (d.get("road_address") or {}).get("address_name")
        jibun = (d.get("address") or {}).get("address_name")
        if road or jibun:
            return {"text": road or jibun, "kind": "address"}
    r = http.get(f"{GEO}/coord2regioncode.json", params=q)
    r.raise_for_status()
    for d in r.json().get("documents", []):
        if d.get("region_type") == "B" and d.get("address_name"):
            return {"text": d["address_name"], "kind": "region"}
    return None


def main() -> None:
    key = get_settings().kakao_rest_key
    if not key:
        raise SystemExit("KAKAO_REST_KEY 가 없습니다")
    http = httpx.Client(headers={"Authorization": f"KakaoAK {key}"}, timeout=10)
    places = [p for p in httpx.get(API, timeout=30).json() if not p.get("address") and p.get("lat")]
    rocks = json.loads(ROCK.read_text(encoding="utf-8"))["points"]
    out: dict = {"place": {}, "rock": {}}
    todo = [("place", p["id"], p["lat"], p["lon"]) for p in places] + [
        ("rock", r["id"], r["lat"], r["lon"]) for r in rocks
    ]
    miss = 0
    for i, (kind, pid, lat, lon) in enumerate(todo, 1):
        hit = lookup(http, lat, lon)
        if hit:
            # 좌표도 같이 남긴다: 서버는 id 와 좌표가 맞을 때만 붙인다 (다른 DB 의 같은 id 오인 방지)
            out[kind][str(pid)] = {**hit, "lat": round(lat, 5), "lon": round(lon, 5)}
        else:
            miss += 1
        time.sleep(0.03)
        if i % 200 == 0:
            print(f"{i}/{len(todo)}")
    OUT.write_text(
        json.dumps(
            {
                "_note": "scripts/build_near_address.py 로 생성. 좌표가 속한 동·리(카카오 좌표→주소). "
                "kind=region 은 번지 없는 동네 이름이라 「근처」로만 표시",
                "source": "카카오 로컬 좌표→주소",
                "generated_at": datetime.now(UTC).date().isoformat(),
                **out,
            },
            ensure_ascii=False,
            indent=0,
        )
        + "\n",
        encoding="utf-8",
    )
    kinds = [v["kind"] for d in out.values() for v in d.values()]
    print(
        f"장소 {len(out['place'])}/{len(places)} · 갯바위 {len(out['rock'])}/{len(rocks)} · "
        f"번지주소 {kinds.count('address')} · 동네만 {kinds.count('region')} · 없음 {miss}"
    )


if __name__ == "__main__":
    main()
