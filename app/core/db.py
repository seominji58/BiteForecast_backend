import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateColumn

from app.core.config import get_settings
from app.models import Base, Species, Title

settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")
_engine_kwargs: dict = {}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    if ":memory:" in settings.database_url:
        _engine_kwargs["poolclass"] = StaticPool

else:
    # Supabase Session pooler: 연결 수가 적으므로 작은 풀, 끊긴 연결은 미리 확인.
    # 오래 쉰 연결은 중간 장비가 조용히 끊는다 → 5분마다 새로 맺고, TCP keepalive 로 끊김을 빨리 알아챈다
    # (2026-11-11 쉬던 연결로 조회하다 2분 가까이 멈춘 뒤 오류)
    _engine_kwargs.update(
        pool_size=5,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        },
    )

engine = create_engine(settings.database_url, **_engine_kwargs)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 칭호 기준 (정의서 FR-12)
DEFAULT_TITLES = [
    ("입문", 0),
    ("초보", 50),
    ("주말", 150),
    ("베테랑", 300),
    ("바다의 고수", 600),
]


# 어종 기준 목록 (바다낚시 주요 어종, 목록에 없으면 앱에서 「기타」로 직접 입력)
DEFAULT_SPECIES = [
    ("rockfish", "우럭(조피볼락)"),
    ("flatfish", "광어(넙치)"),
    ("black_porgy", "감성돔"),
    ("red_seabream", "참돔"),
    ("seabass", "농어"),
    ("black_rockfish", "볼락"),
    ("greenling", "노래미"),
    ("mackerel", "고등어"),
    ("horse_mackerel", "전갱이"),
    ("halfbeak", "학꽁치"),
    ("mullet", "숭어"),
    ("goby", "망둥어"),
    ("webfoot_octopus", "주꾸미"),
    ("cuttlefish", "갑오징어"),
    ("bigfin_squid", "무늬오징어"),
]


def _add_missing_columns() -> list[str]:
    """기존 테이블에 새로 생긴 컬럼만 추가한다 (데이터는 그대로).

    create_all 은 기존 테이블을 바꾸지 않으므로 필요하다.

    추가만 하고 삭제·형 변경은 하지 않는다. 새 컬럼은 NULL 허용이거나 server_default 가 있어야 한다.
    운영 DB 로 옮길 때는 Alembic 마이그레이션으로 대체한다.
    """
    added: list[str] = []
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                if not col.nullable and col.server_default is None:
                    raise RuntimeError(
                        f"{table.name}.{col.name}: NOT NULL 컬럼은 server_default 가 있어야 추가 가능"
                    )
                ddl = (
                    f"ALTER TABLE {table.name} ADD COLUMN {CreateColumn(col).compile(dialect=engine.dialect)}"
                )
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
    return added


def _check_migrated() -> None:
    """PostgreSQL: 표 구조는 Alembic 으로만 바꾼다. 최신 버전이 아니면 서버를 띄우지 않는다"""
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from app.core.migrate import ALEMBIC_INI

    head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    if current != head:
        raise RuntimeError(f"DB 구조 버전 {current} ≠ 최신 {head}: `alembic upgrade head` 를 먼저 실행하세요")


def init_db() -> None:
    """SQLite(개발·테스트): 테이블 생성 + 새 컬럼 추가. PostgreSQL: Alembic 버전 확인만.
    공통: 기준 데이터(칭호·어종)가 비어 있을 때만 시드."""
    if _is_sqlite:
        Base.metadata.create_all(engine)
        added = _add_missing_columns()
        if added:
            logging.getLogger(__name__).info("컬럼 추가: %s", ", ".join(added))
    else:
        _check_migrated()
    with SessionLocal() as db:
        if db.scalar(select(Title.id).limit(1)) is None:
            db.add_all(
                Title(name=name, min_points=pts, sort_order=i) for i, (name, pts) in enumerate(DEFAULT_TITLES)
            )
        if db.scalar(select(Species.code).limit(1)) is None:
            db.add_all(Species(code=code, name_ko=name) for code, name in DEFAULT_SPECIES)
        db.commit()
