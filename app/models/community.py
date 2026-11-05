"""커뮤니티 (조황공유·낚시질문·정보팁). 사용자 생성 콘텐츠이므로 신고·숨김·작성자 삭제를 지원한다."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, str_enum, utcnow


class PostCategory(StrEnum):
    CATCH = "catch"  # 조황공유
    QUESTION = "question"  # 낚시질문
    TIP = "tip"  # 정보·팁


class ReportTarget(StrEnum):
    POST = "post"
    COMMENT = "comment"


class Post(TimestampMixin, Base):
    __tablename__ = "post"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    category: Mapped[PostCategory] = mapped_column(str_enum(PostCategory), index=True)
    title: Mapped[str] = mapped_column(String(60))
    body: Mapped[str] = mapped_column(Text)
    place_id: Mapped[int | None] = mapped_column(ForeignKey("place.id"))
    species_code: Mapped[str | None] = mapped_column(ForeignKey("species.code"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)  # 신고 누적으로 숨김

    comments: Mapped[list["Comment"]] = relationship(back_populates="post")


class Comment(TimestampMixin, Base):
    __tablename__ = "comment"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("post.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)

    post: Mapped[Post] = relationship(back_populates="comments")


class PostLike(TimestampMixin, Base):
    __tablename__ = "post_like"

    post_id: Mapped[int] = mapped_column(ForeignKey("post.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)


class ContentReport(TimestampMixin, Base):
    """신고. 같은 사용자가 같은 대상을 중복 신고할 수 없다"""

    __tablename__ = "content_report"
    __table_args__ = (UniqueConstraint("target_type", "target_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[ReportTarget] = mapped_column(str_enum(ReportTarget))
    target_id: Mapped[int] = mapped_column(index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(String(200))
