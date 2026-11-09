"""좌표 검증 기록 등록·되돌리기 (원본 좌표는 바꾸지 않는다).

마이그레이션 (place_coord_check 테이블 생성 + 감사 결과 등록):
    1) DB 백업:
       sqlite3 biteforecast.db ".backup backups/biteforecast-<시각>-before-coord-check.db"
    2) 등록:
       python scripts/coord_checks.py register <좌표품질_219곳.csv> --batch audit-2026-11-09
       (테이블이 없으면 만든다. 서버 시작 시 create_all 로도 만들어진다)
    3) 확인:     python scripts/coord_checks.py summary

롤백:
    · 이번 등록만 취소:  python scripts/coord_checks.py rollback --batch audit-2026-11-09
    · 테이블까지 제거:   python scripts/coord_checks.py drop-table   (기록이 남아 있으면 거부, --force 로만)
      — 코드에서 PlaceCoordCheck 를 쓰고 있으므로 테이블만 지우면 서버 시작 때 빈 테이블이 다시 생긴다.
        완전히 되돌리려면 해당 커밋을 되돌린 뒤 drop-table 한다. 마지막 수단: 위 1) 백업 파일로 교체
"""

import argparse
import collections
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, text  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.models import PlaceCoordCheck  # noqa: E402
from app.services.coord_checks import RegisterError, register_address_batch, register_from_audit, rollback  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register")
    r.add_argument("csv")
    r.add_argument("--batch", required=True)
    ad = sub.add_parser("register-address")
    ad.add_argument("csv", help="verify_addresses.py --public 출력")
    ad.add_argument("--batch", required=True)
    b = sub.add_parser("rollback")
    b.add_argument("--batch", required=True)
    sub.add_parser("summary")
    d = sub.add_parser("drop-table")
    d.add_argument("--force", action="store_true")
    a = ap.parse_args()

    PlaceCoordCheck.__table__.create(engine, checkfirst=True)
    with SessionLocal() as db:
        if a.cmd == "register":
            rows = list(csv.DictReader(open(a.csv, encoding="utf-8-sig")))
            try:
                n = register_from_audit(db, rows, a.batch)
            except RegisterError as e:
                print("등록 안 함:", e)
                return 1
            print(f"등록 {n}건 (batch {a.batch})")
        elif a.cmd == "register-address":
            rows = list(csv.DictReader(open(a.csv, encoding="utf-8-sig")))
            try:
                n = register_address_batch(db, rows, a.batch)
            except RegisterError as e:
                print("등록 안 함:", e)
                return 1
            print(f"등록 {n}건 (batch {a.batch}) — 등급 변경 없음")
        elif a.cmd == "rollback":
            print(f"삭제 {rollback(db, a.batch)}건 (batch {a.batch}) — 원본 좌표는 그대로")
        elif a.cmd == "drop-table":
            left = db.scalar(select(func.count(PlaceCoordCheck.id))) or 0
            if left and not a.force:
                print(f"기록 {left}건이 남아 있어 지우지 않습니다 (--force)")
                return 1
            db.close()
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS place_coord_check"))
            print("place_coord_check 테이블 삭제")
            return 0
        rows = db.scalars(select(PlaceCoordCheck)).all()
        print("기록", len(rows), "· batch", dict(collections.Counter(x.batch for x in rows)))
        latest = {}
        for x in sorted(rows, key=lambda x: x.id):
            latest[x.place_id] = x
        print("현재 등급", dict(sorted(collections.Counter(x.grade for x in latest.values()).items())))
        print("세부", dict(collections.Counter(x.sub_grade for x in latest.values())))
        print("위치 유형", dict(collections.Counter(x.location_type for x in latest.values())))
        print("검증 상태", dict(collections.Counter(x.status for x in latest.values())))
        print("출처", dict(collections.Counter(x.method for x in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
