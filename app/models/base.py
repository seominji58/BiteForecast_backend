from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def str_enum(enum_cls: type[PyEnum]) -> Enum:
    """DB 에는 문자열 값으로 저장 (SQLite/운영 DB 공통)"""
    return Enum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )
