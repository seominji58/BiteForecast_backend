"""경기도 낚시어선업 현황(경기데이터드림) 확인 — 읽기 전용, DB 에 저장하지 않는다.

  python -m scripts.gyeonggi_fishing_boats --service <서비스명> [--mof-csv <해수부 신고대장 CSV>]

- 서비스명: 경기데이터드림 해당 데이터의 「Open API」 탭 요청 주소
  https://openapi.gg.go.kr/<서비스명> 에서 확인
- 출력: 건수, 응답 항목, 출입항 상위, 입질예보 경기 낚시터와 항구 이름이 겹치는 곳,
  (선택) 해수부 CSV 와 출입항 겹침
- 인증키는 출력하지 않는다. 응답에 없는 좌표·전화번호를 만들지 않는다
"""

import argparse
import collections
import csv
import io
import re
import sys

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.clients.gyeonggi import GyeonggiClient, GyeonggiError
from app.core.db import SessionLocal
from app.models import Place

PORT = re.compile(r"([가-힣]{2,6}항)(?![가-힣])")


def ports(text: str) -> set[str]:
    return set(PORT.findall(text or ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", required=True, help="경기데이터드림 서비스명")
    ap.add_argument("--mof-csv", help="해양수산부 낚시어선업 신고대장 CSV (비교용, 선택)")
    args = ap.parse_args()

    try:
        rows = GyeonggiClient().all(args.service)
    except GyeonggiError as e:
        sys.exit(f"실패: {e}")
    print(f"건수: {len(rows)}")
    if not rows:
        print("자료 없음")
        return
    print("응답 항목:", ", ".join(rows[0].keys()))

    text_fields = [
        k for k in rows[0] if any(isinstance(r.get(k), str) and "항" in r.get(k, "") for r in rows[:50])
    ]
    gg_ports = collections.Counter(p for r in rows for k in text_fields for p in ports(r.get(k)))
    print("출입항(항 이름) 상위:", gg_ports.most_common(10))

    with SessionLocal() as db:
        places = db.scalars(
            select(Place).where(Place.is_active.is_(True)).options(selectinload(Place.region))
        ).all()
    gg_places = [p for p in places if p.region.name.startswith("경기")]
    hits = [
        (p.name, sorted(ports(p.name) & set(gg_ports))) for p in gg_places if ports(p.name) & set(gg_ports)
    ]
    print(f"입질예보 경기 낚시터 {len(gg_places)}곳 중 항구 이름이 겹치는 곳: {len(hits)}")
    for h in hits:
        print("  ", h)

    if args.mof_csv:
        raw = open(args.mof_csv, "rb").read()
        text = raw.decode("cp949", errors="replace")
        mof = [
            r
            for r in csv.DictReader(io.StringIO(text))
            if (r.get("낚시어선영업장소명") or "").startswith("경기")
        ]
        mof_ports = collections.Counter(p for r in mof for p in ports(r.get("출입항명", "")))
        both = set(gg_ports) & set(mof_ports)
        print(
            f"해수부 CSV 경기 행 {len(mof)} · 출입항 겹침 {len(both)}"
            f" / 경기 API {len(gg_ports)} · 해수부 {len(mof_ports)}"
        )


if __name__ == "__main__":
    main()
