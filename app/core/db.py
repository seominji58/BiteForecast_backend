from collections.abc import Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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


def init_db() -> None:
    """개발용: 테이블 생성 + 기준 데이터 시드. 스키마가 안정되면 Alembic 마이그레이션으로 전환."""
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(Title.id).limit(1)) is None:
            db.add_all(
                Title(name=name, min_points=pts, sort_order=i) for i, (name, pts) in enumerate(DEFAULT_TITLES)
            )
        if db.scalar(select(Species.code).limit(1)) is None:
            db.add_all(Species(code=code, name_ko=name) for code, name in DEFAULT_SPECIES)
        db.commit()
