"""개발·검증용 사용자 표시 / 해제. 데이터는 지우지 않고 일반 화면에서만 숨긴다.

사용:
  python -m scripts.mark_test_user 9          # 사용자 9 를 테스트 사용자로
  python -m scripts.mark_test_user 9 --undo   # 되돌리기
  python -m scripts.mark_test_user --list     # 테스트 사용자 목록

숨겨진 글·사진을 개발 중에 보려면 backend/.env 에 SHOW_TEST_DATA=true
"""

import argparse

from sqlalchemy import func, select

from app.core.db import SessionLocal, init_db
from app.models import AppUser, Journal, Photo, Post


def main() -> None:
    ap = argparse.ArgumentParser(description="테스트 사용자 표시")
    ap.add_argument("user_id", nargs="?", type=int)
    ap.add_argument("--undo", action="store_true", help="테스트 표시 해제")
    ap.add_argument("--list", action="store_true", help="테스트 사용자 목록")
    args = ap.parse_args()
    init_db()
    with SessionLocal() as db:
        if args.list or args.user_id is None:
            for u in db.scalars(select(AppUser).where(AppUser.is_test.is_(True))):
                print(f"테스트 사용자 {u.id} ({u.device_id})")
            return
        u = db.get(AppUser, args.user_id)
        if u is None:
            raise SystemExit(f"사용자 {args.user_id} 없음")
        u.is_test = not args.undo
        db.commit()
        n = lambda m: db.scalar(select(func.count()).select_from(m).where(m.user_id == u.id))  # noqa: E731
        state = "테스트 사용자로 표시" if u.is_test else "테스트 표시 해제"
        print(
            f"사용자 {u.id}: {state} (글 {n(Post)} · 기록 {n(Journal)} · 사진 {n(Photo)}, 데이터 변경 없음)"
        )


if __name__ == "__main__":
    main()
