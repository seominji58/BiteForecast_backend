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


def init_db() -> None:
    """개발용: 테이블 생성 + 새 컬럼 추가 + 기준 데이터 시드."""
    Base.metadata.create_all(engine)
    added = _add_missing_columns()
    if added:
        logging.getLogger(__name__).info("컬럼 추가: %s", ", ".join(added))
    with SessionLocal() as db:
        if db.scalar(select(Title.id).limit(1)) is None:
            db.add_all(
                Title(name=name, min_points=pts, sort_order=i) for i, (name, pts) in enumerate(DEFAULT_TITLES)
            )
        if db.scalar(select(Species.code).limit(1)) is None:
            db.add_all(Species(code=code, name_ko=name) for code, name in DEFAULT_SPECIES)
        db.commit()
