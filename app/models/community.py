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
    FREE = "free"  # 자유게시판 (낚시 말고도 아무 이야기). DB 는 문자열 칸이라 마이그레이션 없음


class LocationVisibility(StrEnum):
    """글의 위치 공개 범위 (낚시터 이름은 공공 낚시터 목록의 이름이지 사용자 GPS 가 아니다)"""

    PLACE = "place"  # 낚시터 이름까지
    REGION = "region"  # 지역(시·군)만
    HIDDEN = "hidden"  # 위치 숨김


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
    # 낚시터 없이 지역만 고른 글 (낚시터를 고르면 그 낚시터의 지역을 쓴다)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region.id"))
    # 위치 공개 범위. 기존 글은 낚시터를 공개한 상태로 올라갔으므로 place
    location_visibility: Mapped[LocationVisibility] = mapped_column(
        str_enum(LocationVisibility),
        default=LocationVisibility.REGION,
        server_default=LocationVisibility.PLACE.value,
    )
    species_code: Mapped[str | None] = mapped_column(ForeignKey("species.code"))
    species_etc: Mapped[str | None] = mapped_column(String(50))  # 목록에 없는 어종 직접 입력
    # 공유한 내 낚시일지 (인증 완료면 「인증 조황」 배지). 포인트는 일지에서만 계산 — 글로는 지급 안 함
    journal_id: Mapped[int | None] = mapped_column(ForeignKey("journal.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)  # 신고 누적으로 숨김
    # 공유한 기록의 미끼·채비를 글에 함께 보여줄지 (기존 글은 동의 전이므로 false)
    show_tackle: Mapped[bool] = mapped_column(Boolean, default=True, server_default="0")

    comments: Mapped[list["Comment"]] = relationship(back_populates="post")


class Comment(TimestampMixin, Base):
    __tablename__ = "comment"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("post.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    # 대댓글: 원댓글 id (한 단계만 — 답글에 다시 답글은 달 수 없다). 원댓글이면 None
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comment.id", ondelete="CASCADE"), index=True)
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
    # 관리자가 검토(숨김 유지·해제)한 시각. 자동 숨김 기준은 검토 전 신고만 센다
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class UserBlock(TimestampMixin, Base):
    """사용자 차단: 차단한 사람에게 차단된 사람의 글·댓글이 보이지 않는다 (상대에게 알리지 않음)"""

    __tablename__ = "user_block"

    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    blocked_user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
