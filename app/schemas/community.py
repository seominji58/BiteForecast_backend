from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.community import LocationVisibility, PostCategory, ReportTarget
from app.schemas.photo import PhotoOut


def _strip(v):
    return v.strip() if isinstance(v, str) else v


class AuthorOut(BaseModel):
    nickname: str  # 계정 닉네임. 계정 없는 예전 기기 사용자는 「이전 사용자」
    title: str  # 현재 칭호


class PostIn(BaseModel):
    category: PostCategory
    title: str = Field(min_length=2, max_length=60)
    body: str = Field(min_length=1, max_length=2000)
    place_id: int | None = None
    # 낚시터 없이 지역만 고를 때 (GET /regions 의 id). 낚시터를 고르면 무시하고 그 낚시터의 지역을 쓴다
    region_id: int | None = None
    # 위치 공개 범위 — 기본은 지역만
    location_visibility: LocationVisibility = LocationVisibility.REGION
    species_code: str | None = Field(default=None, max_length=30)
    species_etc: str | None = Field(default=None, max_length=50)  # 목록에 없는 어종
    # 업로드해 둔 일반 게시글 사진 ID (최대 4장, 포인트 무관)
    photo_ids: list[int] = Field(default_factory=list, max_length=10)
    # 내 낚시일지 공유 (조황공유 글). 장소·어종·사진은 일지 것을 쓴다. 인증 완료면 「인증 조황」 배지
    journal_id: int | None = None

    _s = field_validator("title", "body", mode="before")(_strip)

    @field_validator("species_code", "species_etc", mode="before")
    @classmethod
    def _blank(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @model_validator(mode="after")
    def _one_species(self):
        if self.species_code and self.species_etc:
            raise ValueError("어종은 목록 선택과 직접 입력 중 하나만 입력합니다")
        return self


class CatchOut(BaseModel):
    """공유한 일지의 조과 (공유 글에 표시)"""

    fished_at: datetime
    species_name: str | None
    count: int | None
    max_length_cm: float | None


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
    # 인증 완료 일지를 공유한 글 (「인증 조황」 배지)
    verified: bool
    # 위치 공개 범위. place 가 아니면 place_name·place_id 는 비어 있고, hidden 이면 region_name 도 비어 있다
    location_visibility: LocationVisibility
    photo_count: int
    thumb: PhotoOut | None
    place_id: int | None
    region_name: str | None  # 예: 「제주 제주시」
    # 기록 공유 글의 조과 (기록에서 가져옴, 인증이 반려된 기록은 None). 일반 글은 None
    catch: CatchOut | None


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
    photos: list[PhotoOut]


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
