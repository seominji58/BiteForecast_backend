from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """시각은 UTC 로 저장하고 tz-aware(UTC) 로 읽는다.

    SQLite 는 시간대 정보를 보존하지 않으므로, 이 타입 없이 저장하면 오프셋이 사라진다.
    timezone 이 없는 값은 받지 않는다 (어느 시간대인지 알 수 없으므로).
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timezone 이 없는 datetime 은 저장할 수 없습니다")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


def str_enum(enum_cls: type[PyEnum]) -> Enum:
    """DB 에는 문자열 값으로 저장 (SQLite/운영 DB 공통)"""
    return Enum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )
