"""낚시터 근처 「예년 같은 달」 수온 (2026-11-24).

실측 수온과 비교해 「평년보다 +1.8°C」를 보여주기 위한 기준값.

자료 (seeds, 국립수산과학원):
- sea_temp_recent.json: 실시간 해양수산환경 관측 2019~2025 월평균
  (147곳, 위치는 관측소 이름으로 찾은 대략 위치)
- sea_temp_normals.json: 연안정지관측 2005~2017 월평균 (34곳, 정확한 위치)
같은 바다 관측소 중 50km 안 가장 가까운 곳 — 최근 자료를 먼저, 없으면 평년 자료.
월평균과 하루 실측을 비교하는 참고값이다 (판정에 쓰지 않음).
"""

import json
from functools import lru_cache
from pathlib import Path

from app.core.geo import haversine_km
from app.schemas.summary import TempNormalOut

SEEDS = Path(__file__).resolve().parent.parent.parent / "seeds"
MAX_KM = 50.0


@lru_cache(maxsize=1)
def _tables() -> list[tuple[str, str, list[dict]]]:
    out = []
    for name, period in (("sea_temp_recent.json", "2019~2025"), ("sea_temp_normals.json", "2005~2017")):
        path = SEEDS / name
        if path.exists():
            out.append(
                (
                    period,
                    json.loads(path.read_text(encoding="utf-8"))["source"],
                    json.loads(path.read_text(encoding="utf-8"))["stations"],
                )
            )
    return out


def normal_for(lat: float | None, lon: float | None, sea: str | None, month: int) -> TempNormalOut | None:
    if lat is None or lon is None:
        return None
    for period, source, stations in _tables():
        best = None
        for st in stations:
            v = st.get("monthly", {}).get(str(month))
            if v is None or (sea and st.get("sea") and st["sea"] != sea):
                continue
            d = haversine_km(lat, lon, st["lat"], st["lon"])
            if d <= MAX_KM and (best is None or d < best[0]):
                best = (d, st, v)
        if best:
            d, st, v = best
            return TempNormalOut(
                v=v,
                station=st.get("name") or st.get("station", ""),
                km=round(d, 1),
                period=period,
                source=source,
            )
    return None
