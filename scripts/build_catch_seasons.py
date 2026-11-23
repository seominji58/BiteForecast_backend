"""어종별 월별 어획량 → 「많이 잡히는 달」 (통계청 어업생산동향조사, KOSIS DT_1EW0004) — 2026-11-23.

- 연근해어업(바다 어획, 양식 제외) · 생산량(톤) · 판매형태 계 · 월별
- 바다 단위로 시도를 묶는다: 서해(인천·경기·충남·전북) · 남해(부산·경남·전남·전남광주통합)
  · 동해(강원·경북·울산) · 제주
- 최근 5년(2021~2025) 같은 달끼리 평균 → 1년 중 비율(%)
- 그 어종 월 평균의 1.3배 이상인 달을 「많이 잡히는 달」로
- 어선 어획 기준이라 낚시 조과와 같지 않다. 앱은 「어획 많은 달」로만 표시한다
- 금어기 달은 0에 가까워 자연히 빠진다

실행: KOSIS_API_KEY 가 .env 에 있어야 한다
  .venv/bin/python -m scripts.build_catch_seasons
→ seeds/catch_seasons.json
"""

import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "seeds" / "catch_seasons.json"
URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
YEARS = (2021, 2025)
PEAK = 1.3

# 앱 어종 코드 → KOSIS 연근해어업 품종 코드 (품종명은 메타데이터로 확인)
SPECIES = {
    "black_porgy": ("감성돔", "110048"),
    "red_seabream": ("참돔", "110057"),
    "rockfish": ("조피볼락", "110099"),
    "greenling": ("노래미류", "110103"),
    "flatfish": ("넙치류", "110024"),
    "seabass": ("농어류", "110030"),
    "spanish_mackerel": ("삼치류", "110108"),
    "yellowtail": ("방어류", "110078"),
    "hairtail": ("갈치", "110009"),
    "mackerel": ("고등어", "110015"),
    "webfoot_octopus": ("주꾸미", "140415"),
    "cuttlefish": ("갑오징어류", "140403"),
    "mitre_squid": ("한치류", "140420"),
    "octopus": ("문어류", "140412"),
    "filefish": ("쥐치류", "110171"),
    "horse_mackerel": ("전갱이류", "110153"),
    "halfbeak": ("학공치", "110021"),
    "mullet": ("숭어류", "110126"),
    "sillago": ("보리멸", "110093"),
    "goby": ("망둑어류", "110063"),
    "conger": ("붕장어", "110150"),
    "gizzard_shad": ("전어", "110156"),
    "flounder": ("가자미류", "110006"),
    "croaker": ("민어", "110075"),
}
SEAS = {
    "서해": ["23", "31", "34", "35"],
    "남해": ["21", "38", "36", "12"],
    "동해": ["32", "37", "26"],
    "제주": ["39"],
}


def _key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("KOSIS_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("KOSIS_API_KEY 가 .env 에 없습니다")


def _get(http: httpx.Client, key: str, species: str, sido: str) -> list[dict]:
    params = {
        "method": "getList",
        "apiKey": key,
        "orgId": "101",
        "tblId": "DT_1EW0004",
        "itmId": "T01",
        "objL1": "1",
        "objL2": species,
        "objL3": sido,
        "objL4": "0",
        "objL5": "",
        "objL6": "",
        "objL7": "",
        "objL8": "",
        "format": "json",
        "jsonVD": "Y",
        "prdSe": "M",
        "startPrdDe": f"{YEARS[0]}01",
        "endPrdDe": f"{YEARS[1]}12",
    }
    for attempt in range(3):
        try:
            d = http.get(URL, params=params).json()
            return d if isinstance(d, list) else []
        except (httpx.HTTPError, ValueError):
            time.sleep(2 * (attempt + 1))
    return []


def main() -> None:
    key = _key()
    http = httpx.Client(timeout=60)
    out = {}
    for code, (name, kc) in SPECIES.items():
        seas = {}
        for sea, sidos in SEAS.items():
            month_tons: dict[int, list[float]] = defaultdict(list)
            by_ym: dict[tuple[int, int], float] = defaultdict(float)
            for s in sidos:
                for row in _get(http, key, kc, s):
                    try:
                        v = float(row["DT"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    ym = row["PRD_DE"]
                    by_ym[(int(ym[:4]), int(ym[4:6]))] += v
                time.sleep(0.15)
            for (_y, m), v in by_ym.items():
                month_tons[m].append(v)
            avg = {m: sum(v) / len(v) for m, v in month_tons.items() if v}
            total = sum(avg.values())
            if total < 12:  # 1년 평균 12톤 미만(월 1톤 미만)이면 통계로 보기 어려워 뺀다
                continue
            mean = total / 12
            seas[sea] = {
                "share": {str(m): round(100 * avg.get(m, 0) / total, 1) for m in range(1, 13)},
                "peak": [m for m in range(1, 13) if avg.get(m, 0) >= PEAK * mean],
                "tons_per_year": round(total),
            }
        out[code] = {"name": name, "kosis_code": kc, "seas": seas}
        print(code, name, {k: v["peak"] for k, v in seas.items()})
    OUT.write_text(
        json.dumps(
            {
                "_note": "scripts/build_catch_seasons.py 로 생성 — 직접 고치지 말 것",
                "source": "통계청 어업생산동향조사 (KOSIS DT_1EW0004), 연근해어업 생산량",
                "period": f"{YEARS[0]}~{YEARS[1]} 월평균",
                "method": f"바다별 월평균 어획량의 1년 비율, "
                f"월 평균의 {PEAK}배 이상인 달을 「어획 많은 달」로",
                "notice": "어선 어획 통계예요. 낚시 조과와 같지 않고, 해마다·지역마다 달라요.",
                "generated_at": datetime.now(UTC).date().isoformat(),
                "species": out,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(out)}종 → {OUT.name}")


if __name__ == "__main__":
    main()
