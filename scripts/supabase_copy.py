"""SQLite → Supabase(PostgreSQL) 사본 만들기 (2026-11-11 사용자 승인)

앱은 계속 SQLite 를 쓴다. 이 스크립트는 그 시점의 사본을 Supabase 에 만들고 검증만 한다.

  python -m scripts.supabase_copy copy     # 표 만들기 + 복사 (대상에 표·행이 있으면 거부)
  python -m scripts.supabase_copy verify   # 행 수·표본·좌표·검증 이력 대조
  python -m scripts.supabase_copy lockdown # 공개 역할(anon·authenticated) 권한 회수 + RLS
  python -m scripts.supabase_copy drop --yes  # 이 스크립트가 만든 표만 삭제 (되돌리기)

- 연결 주소는 backend/.env 의 SUPABASE_DATABASE_URL. 주소·비밀번호는 출력하지 않는다
- SQLite 는 읽기 전용으로 연다 (원본 변경 없음)
- 시드는 넣지 않는다 (init_db 를 부르지 않음). ID 는 원본 그대로, 복사 뒤 다음 번호를 맞춘다
- journal_photo(예전 표, 모델에 없음)는 옮기지 않는다
"""

import argparse
import random
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, inspect, select, text

import app.models  # noqa: F401  모델 등록
from app.models.base import Base

ROOT = Path(__file__).resolve().parent.parent
SQLITE = ROOT / "biteforecast.db"
BATCH = 2000
SAMPLE = 200


def _target_url() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("SUPABASE_DATABASE_URL="):
            url = line.split("=", 1)[1].strip()
            if not url.startswith("postgresql://"):
                sys.exit("SUPABASE_DATABASE_URL 이 postgresql:// 주소가 아닙니다")
            return "postgresql+psycopg://" + url[len("postgresql://") :]
    sys.exit("backend/.env 에 SUPABASE_DATABASE_URL 이 없습니다")


def _redact(e: Exception) -> str:
    return re.sub(r"postgres(ql)?(\+psycopg)?://\S+", "postgresql://***", str(e))[:300]


def _engines():
    src = create_engine(f"sqlite:///file:{SQLITE}?mode=ro&uri=true")
    dst = create_engine(_target_url(), pool_pre_ping=True)
    return src, dst


TABLES = Base.metadata.sorted_tables  # 외래키 순서
SERIAL_SEQ = text("select pg_get_serial_sequence(:t, :c)")


def lockdown(conn) -> None:
    """Supabase 공개 역할(anon·authenticated)이 이 표들에 접근하지 못하게 한다.
    백엔드는 postgres(소유자)로 접속하므로 영향이 없다. RLS 는 정책 없이 켜서 공개 역할은 모두 거부"""
    names = [t.name for t in TABLES]
    for n in names:
        conn.execute(text(f'revoke all on table public."{n}" from anon, authenticated'))
        conn.execute(text(f'alter table public."{n}" enable row level security'))
    conn.execute(text("revoke usage, select on all sequences in schema public from anon, authenticated"))
    # 앞으로 만드는 표·시퀀스도 자동 공개하지 않음
    for obj in ("tables", "sequences", "functions"):
        q = f"alter default privileges in schema public revoke all on {obj} from anon, authenticated"
        conn.execute(text(q))


def copy() -> None:
    src, dst = _engines()
    existing = set(inspect(dst).get_table_names(schema="public"))
    clash = existing & {t.name for t in TABLES}
    if clash:
        sys.exit(f"대상에 이미 표가 있어 복사하지 않습니다: {sorted(clash)[:5]}… (되돌리기: drop --yes)")
    with dst.begin() as conn:  # 표 생성 + 복사를 한 트랜잭션으로 — 실패하면 아무것도 남지 않는다
        Base.metadata.create_all(conn)
        lockdown(conn)
        for t in TABLES:
            n = 0
            with src.connect() as s:
                rows = s.execute(select(t)).mappings()
                batch = []
                for r in rows:
                    batch.append(dict(r))
                    if len(batch) >= BATCH:
                        conn.execute(t.insert(), batch)
                        n += len(batch)
                        batch = []
                if batch:
                    conn.execute(t.insert(), batch)
                    n += len(batch)
            # 다음 ID 번호를 원본 최댓값 뒤로
            for c in t.primary_key.columns:
                if c.autoincrement is True or (c.autoincrement == "auto" and c.type.python_type is int):
                    seq = conn.scalar(SERIAL_SEQ, {"t": t.name, "c": c.name})
                    if seq:
                        nxt = f"coalesce((select max({c.name}) from {t.name}), 0) + 1"
                        conn.execute(text(f"select setval('{seq}', {nxt}, false)"))
            print(f"{t.name}: {n}")
    print("복사 완료")


def _norm(v):
    return round(v, 9) if isinstance(v, float) else v


def check_exposure(d) -> bool:
    grants = d.scalar(text(
        "select count(*) from information_schema.role_table_grants "
        "where table_schema='public' and grantee in ('anon','authenticated')"
    ))
    no_rls = d.scalar(text(
        "select count(*) from pg_class where relnamespace='public'::regnamespace and relkind='r' "
        "and not relrowsecurity"
    ))
    mark = "OK " if not grants and not no_rls else "틀림"
    print(f"{mark} 공개 역할 권한 {grants}건 · RLS 꺼진 표 {no_rls}개")
    return not grants and not no_rls


def verify() -> None:
    src, dst = _engines()
    ok = True
    rnd = random.Random(20261111)
    with src.connect() as s, dst.connect() as d:
        for t in TABLES:
            a = s.scalar(select(func.count()).select_from(t))
            b = d.scalar(select(func.count()).select_from(t))
            pk = list(t.primary_key.columns)
            ids = [tuple(r) for r in s.execute(select(*pk))]
            # 좌표·검증 이력은 전부, 나머지는 표본
            full = t.name in ("place", "place_coord_check")
            pick = ids if full else rnd.sample(ids, min(SAMPLE, len(ids)))
            diff = 0
            for key in pick:
                cond = [c == v for c, v in zip(pk, key, strict=True)]
                ra = s.execute(select(t).where(*cond)).mappings().one()
                rb = d.execute(select(t).where(*cond)).mappings().one_or_none()
                if rb is None or {k: _norm(v) for k, v in ra.items()} != {k: _norm(v) for k, v in rb.items()}:
                    diff += 1
            seq_ok = True
            if len(pk) == 1 and pk[0].type.python_type is int and a:
                seq = d.scalar(SERIAL_SEQ, {"t": t.name, "c": pk[0].name})
                if seq:
                    q = f"select last_value + (case when is_called then 1 else 0 end) from {seq}"
                    nxt = d.scalar(text(q))
                    seq_ok = nxt > d.scalar(select(func.max(pk[0])).select_from(t))
            good = a == b and diff == 0 and seq_ok
            ok &= good
            mark = "OK " if good else "틀림"
            print(f"{mark} {t.name}: 행 {a}/{b} · 대조 {len(pick)}{'(전부)' if full else ''} 불일치 {diff}"
                  + ("" if seq_ok else " · 다음 ID 번호 문제"))
        ok &= check_exposure(d)
    print("검증 통과" if ok else "검증 실패")
    if not ok:
        sys.exit(1)


def drop(yes: bool) -> None:
    if not yes:
        sys.exit("되돌리기는 --yes 를 붙여야 합니다 (이 스크립트가 만든 표만 삭제)")
    _, dst = _engines()
    names = {t.name for t in TABLES}
    with dst.begin() as conn:
        present = set(inspect(conn).get_table_names(schema="public")) & names
        Base.metadata.drop_all(conn, tables=[t for t in TABLES if t.name in present])
    print(f"삭제한 표 {len(present)}개")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["copy", "verify", "lockdown", "drop"])
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    try:
        if args.cmd == "lockdown":
            with _engines()[1].begin() as conn:
                lockdown(conn)
            print("공개 역할 권한 회수·RLS 켬")
            return
        {"copy": copy, "verify": verify}.get(args.cmd, lambda: drop(args.yes))()
    except SystemExit:
        raise
    except Exception as e:  # 주소·비밀번호가 메시지에 섞이지 않게
        sys.exit(f"실패: {type(e).__name__}: {_redact(e)}")


if __name__ == "__main__":
    main()
