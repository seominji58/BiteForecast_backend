"""출조계획 테이블 상태 확인 · 롤백 (docs/05_UX/2026-11-09_출조계획_설계안.md).

마이그레이션 (추가만 — 기존 데이터 변경 없음):
    1) 백업:  sqlite3 biteforecast.db ".backup backups/biteforecast-<시각>-before-trip.db"
    2) 서버 시작 시 자동: create_all 이 trip_plan · trip_stop · trip_checklist_item 을 만들고,
       _add_missing_columns 가 journal.trip_stop_id (NULL 허용) 를 더한다. 기존 행은 그대로.
    3) 확인:  python scripts/trip_tables.py status

롤백:
    1) 백업 (위와 같음)
    2) 출조계획 관련 커밋을 되돌린다 (그대로 두면 서버 시작 때 테이블이 다시 생긴다)
    3) python scripts/trip_tables.py rollback          ← 계획이 하나라도 있으면 거부
       python scripts/trip_tables.py rollback --force  ← 계획까지 지움 (백업 확인 후에만)
       · journal.trip_stop_id 를 비우고 칸을 지운 뒤 세 테이블을 지운다. 기록(journal) 자체는 남는다
    마지막 수단: 1) 의 백업 파일로 교체
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402

from app.core.db import engine  # noqa: E402

TABLES = ("trip_checklist_item", "trip_stop", "trip_plan")


def status() -> dict:
    insp = inspect(engine)
    have = set(insp.get_table_names())
    out = {}
    with engine.connect() as c:
        for t in TABLES:
            out[t] = c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() if t in have else "없음"
        cols = {x["name"] for x in insp.get_columns("journal")}
        if "trip_stop_id" in cols:
            linked = c.execute(text("SELECT COUNT(*) FROM journal WHERE trip_stop_id IS NOT NULL")).scalar()
            out["journal.trip_stop_id"] = f"있음 (연결된 기록 {linked}건)"
        else:
            out["journal.trip_stop_id"] = "없음"
        out["journal 전체"] = c.execute(text("SELECT COUNT(*) FROM journal")).scalar()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    r = sub.add_parser("rollback")
    r.add_argument("--force", action="store_true")
    a = ap.parse_args()

    st = status()
    if a.cmd == "status":
        for k, v in st.items():
            print(f"{k}: {v}")
        return 0
    plans = st["trip_plan"] if isinstance(st["trip_plan"], int) else 0
    if plans and not a.force:
        print(f"출조계획 {plans}개가 있어 롤백하지 않습니다. 백업을 확인한 뒤 --force 로 실행하세요.")
        return 1
    with engine.begin() as c:
        if "trip_stop_id" in {x["name"] for x in inspect(engine).get_columns("journal")}:
            c.execute(text("UPDATE journal SET trip_stop_id = NULL"))
            c.execute(text("ALTER TABLE journal DROP COLUMN trip_stop_id"))
        for t in TABLES:
            c.execute(text(f"DROP TABLE IF EXISTS {t}"))
    print("출조계획 테이블·기록 연결 칸 삭제 완료. 기록(journal) 행은 그대로입니다.")
    for k, v in status().items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
