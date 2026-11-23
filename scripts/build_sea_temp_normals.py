"""연안 월평균 수온 (평년) — 국립수산과학원 연안정지관측 (2026-11-23).

- 원자료: 국립수산과학원 OpenAPI 연안정지관측정보(cooList, 매일 표층 수온)·관측소(cooCode)
- 2005~2017년: 관측소가 20~39곳으로 많던 기간 (2019년 이후는 3~4곳만 남음)
- 관측소별 「연-월 평균」을 먼저 구하고, 그 연-월 평균들의 평균을 그 달 평년값으로 쓴다
  (한 해에 관측일이 15일 미만인 달은 뺀다). 한 달에 5개 연도 미만이면 그 달은 비운다
- 이상값: 수온이 -2℃ 미만이거나 35℃ 초과면 뺀다

실행: NIFS_API_KEY 가 .env 에 있어야 한다
  .venv/bin/python -m scripts.build_sea_temp_normals
→ seeds/sea_temp_normals.json
"""

import calendar
import json
import statistics
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "seeds" / "sea_temp_normals.json"
BASE = "https://www.nifs.go.kr/api/OpenAPI_json"
YEARS = range(2005, 2018)
MIN_DAYS = 15
MIN_YEARS = 5


def _key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("NIFS_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("NIFS_API_KEY 가 .env 에 없습니다")


def _get(http: httpx.Client, key: str, **params) -> list[dict]:
    for attempt in range(3):
        try:
            r = http.get(BASE, params={"key": key, **params})
            r.raise_for_status()
            return (r.json().get("body") or {}).get("item") or []
        except (httpx.HTTPError, ValueError):
            time.sleep(2 * (attempt + 1))
    raise SystemExit(f"수산과학원 API 실패: {params.get('id')} {params.get('sdate', '')}")


def main() -> None:
    key = _key()
    http = httpx.Client(headers={"User-Agent": "BiteForecast/1.0"}, timeout=60, follow_redirects=True)
    stations = {}
    for g in "EWS":
        for s in _get(http, key, id="cooCode", gru_nam=g):
            stations[s["sta_cde"]] = s
    # (관측소, 연, 월) → 일별 수온들
    days: dict[tuple[str, int, int], list[float]] = defaultdict(list)
    for y in YEARS:
        for m in range(1, 13):
            last = calendar.monthrange(y, m)[1]
            for it in _get(http, key, id="cooList", sdate=f"{y}{m:02d}01", edate=f"{y}{m:02d}{last}"):
                try:
                    t = float(it["wtr_tmp"])
                except (TypeError, ValueError, KeyError):
                    continue
                if -2 <= t <= 35:
                    days[(it["sta_cde"], y, m)].append(t)
            time.sleep(0.2)
        print(y, "완료")
    # 관측소별 월 평년값
    per: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for (sc, _y, m), ts in days.items():
        if len(ts) >= MIN_DAYS:
            per[sc][m].append(statistics.fmean(ts))
    out = []
    for sc, months in sorted(per.items()):
        s = stations.get(sc)
        if not s or not s.get("lat"):
            continue
        normals = {str(m): round(statistics.fmean(v), 1) for m, v in months.items() if len(v) >= MIN_YEARS}
        if len(normals) < 12:
            continue  # 1년 내내 평년값이 있는 관측소만
        out.append(
            {
                "code": sc,
                "name": s["sta_nam_kor"],
                "sea": s["gru_nam"],
                "lat": float(s["lat"]),
                "lon": float(s["lon"]),
                "monthly": normals,
                "years": {str(m): len(v) for m, v in months.items()},
            }
        )
    OUT.write_text(
        json.dumps(
            {
                "_note": "scripts/build_sea_temp_normals.py 로 생성 — 직접 고치지 말 것",
                "source": "국립수산과학원 연안정지관측정보 (표층 수온, 일 1회)",
                "period": f"{YEARS.start}~{YEARS.stop - 1}",
                "method": f"관측소별 연-월 평균(관측일 {MIN_DAYS}일 이상)의 평균, "
                f"{MIN_YEARS}개 연도 이상인 달만",
                "generated_at": datetime.now(UTC).date().isoformat(),
                "stations": out,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"관측소 {len(out)}곳 → {OUT.name}")


if __name__ == "__main__":
    main()
