from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.community import PostCategory, ReportTarget


def _strip(v):
    return v.strip() if isinstance(v, str) else v


class AuthorOut(BaseModel):
    nickname: str  # 로그인 없음: 기기 사용자 번호 기반 「낚시인0012」
    title: str  # 현재 칭호


class PostIn(BaseModel):
    category: PostCategory
    title: str = Field(min_length=2, max_length=60)
    body: str = Field(min_length=1, max_length=2000)
    place_id: int | None = None
    species_code: str | None = Field(default=None, max_length=30)

    _s = field_validator("title", "body", mode="before")(_strip)


class PostSummaryOut(BaseModel):
    id: int
    category: PostCategory
    title: str
    excerpt: str
    author: AuthorOut
    place_name: str | None
    species_name: str | None
    like_count: int
    comment_count: int
    liked: bool
    mine: bool
    popular: bool
    created_at: datetime


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=500)

    _s = field_validator("body", mode="before")(_strip)


class CommentOut(BaseModel):
    id: int
    body: str
    author: AuthorOut
    mine: bool
    created_at: datetime


class PostDetailOut(PostSummaryOut):
    body: str
    comments: list[CommentOut]


class LikeOut(BaseModel):
    liked: bool
    like_count: int


class ReportIn(BaseModel):
    target_type: ReportTarget
    target_id: int
    reason: str = Field(min_length=1, max_length=200)


class ReportOut(BaseModel):
    status: Literal["received", "already_reported"]
    hidden: bool  # 이번 신고로 숨김 처리됐는지
