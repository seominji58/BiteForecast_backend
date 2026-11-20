"""좌표 근처 주소 (seeds/near_address.json, scripts/build_near_address.py 로 생성) — 2026-11-20.

주소 칸이 없는 장소·갯바위 포인트에 「좌표가 속한 동·리」를 붙인다.
- kind="address": 카카오가 좌표에서 찾은 가장 가까운 번지 주소
- kind="region" : 번지가 없는 바다·바위 좌표라 동·리 이름만 → 앱에서 「○○리 근처」
id 와 좌표가 모두 맞을 때만 준다 (다른 DB 의 같은 id 에 엉뚱한 동네가 붙지 않게).
"""

import json
from functools import lru_cache
from pathlib import Path

_FILE = Path(__file__).resolve().parent.parent.parent / "seeds" / "near_address.json"
_TOL = 0.0005  # 약 50m


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def near(group: str, pid: int, lat: float | None, lon: float | None) -> tuple[str, str] | None:
    """(주소 글자, 'address'|'region') 또는 None"""
    hit = _data().get(group, {}).get(str(pid))
    if not hit or lat is None or lon is None:
        return None
    if abs(hit["lat"] - lat) > _TOL or abs(hit["lon"] - lon) > _TOL:
        return None
    return hit["text"], hit["kind"]
