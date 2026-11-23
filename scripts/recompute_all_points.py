"""모든 사용자 포인트를 지금 규칙으로 다시 계산 (2026-11-23 활동 포인트 전환 때 한 번).

규칙이 「인증 완료 기록만」 → 「기록·글·댓글 활동」으로 바뀌어, 기존 사용자의 원장을 새 기대값에 맞춘다.
원장은 append-only 라 차이만 행으로 더한다 (여러 번 실행해도 같은 결과).

실행: DATABASE_URL=... python scripts/recompute_all_points.py          (미리 보기: 바뀔 사람·합계)
      DATABASE_URL=... python scripts/recompute_all_points.py --apply
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import AppUser  # noqa: E402
from app.services.points import recompute_points  # noqa: E402


def main(apply: bool) -> None:
    db = SessionLocal()
    changed = 0
    total = 0
    for u in db.scalars(select(AppUser).where(AppUser.deleted_at.is_(None))).all():
        d = recompute_points(db, u)
        if d:
            changed += 1
            total += d
            print(f"  사용자 {u.id}: {d:+d}P")
    print(f"{'적용' if apply else '미리 보기'}: {changed}명, 합계 {total:+d}P")
    if apply:
        db.commit()
    else:
        db.rollback()
    db.close()


if __name__ == "__main__":
    main("--apply" in sys.argv)
