"""최근 월평균 수온 (2019~2025) — 국립수산과학원 실시간 해양수산환경 관측시스템 과거자료 (2026-11-23).

원자료: 06_개발환경/data_raw/nifs_실시간수온/<연도>/{es,ys,ss}_<연도>.zip
  (동해·서해·남해, 월별 CSV, 1시간 간격)
- 표층수온만 쓴다. -2℃ 미만·35℃ 초과는 뺀다
- 관측소별 연-월 평균(관측 시각 240개 이상 ≈ 10일)을 먼저 구하고, 연도들의 평균을 그 달 값으로 쓴다
- 3개 연도 이상 있는 달만 남긴다. 좌표는 원자료에 없어 관측소 이름(괄호 안 코드)만 남긴다
→ 06_개발환경/data_raw/nifs_실시간수온/monthly_by_station.json (중간 산출물, 좌표 붙이기 전)
"""

import csv
import io
import json
import statistics
import zipfile
from collections import defaultdict
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "06_개발환경" / "data_raw" / "nifs_실시간수온"
OUT = RAW / "monthly_by_station.json"
SEA = {"es": "동해", "ys": "서해", "ss": "남해"}
MIN_HOURS = 240
MIN_YEARS = 3


def main() -> None:
    acc: dict[tuple[str, str, int, int], list[float]] = defaultdict(list)
    for ydir in sorted(p for p in RAW.iterdir() if p.is_dir()):
        for zpath in sorted(ydir.glob("*.zip")):
            sea = SEA.get(zpath.name[:2])
            with zipfile.ZipFile(zpath) as z:
                for info in z.infolist():
                    if not info.filename.lower().endswith(".csv"):
                        continue
                    text = z.read(info).decode("cp949", "replace")
                    for row in csv.DictReader(io.StringIO(text)):
                        try:
                            t = float(row["표층수온(℃)"])
                        except (TypeError, ValueError, KeyError):
                            continue
                        if not -2 <= t <= 35:
                            continue
                        when = row["관측일시"]
                        acc[(row["관측소"], sea, int(when[:4]), int(when[5:7]))].append(t)
            print(zpath.name, "완료")
    per: dict[tuple[str, str], dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for (st, sea, _y, m), ts in acc.items():
        if len(ts) >= MIN_HOURS:
            per[(st, sea)][m].append(statistics.fmean(ts))
    out = []
    for (st, sea), months in sorted(per.items()):
        monthly = {str(m): round(statistics.fmean(v), 1) for m, v in months.items() if len(v) >= MIN_YEARS}
        if monthly:
            out.append(
                {
                    "station": st,
                    "sea": sea,
                    "monthly": monthly,
                    "years": {str(m): len(v) for m, v in months.items()},
                }
            )
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    full = sum(1 for s in out if len(s["monthly"]) == 12)
    print(f"관측소 {len(out)}곳 (12개월 다 있는 곳 {full}) → {OUT}")


if __name__ == "__main__":
    main()
