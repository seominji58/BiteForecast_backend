from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, Reader
from app.models.community import PostCategory
from app.schemas.community import (
    CommentIn,
    LikeOut,
    PostDetailOut,
    PostIn,
    PostSummaryOut,
    ReportIn,
    ReportOut,
)
from app.services import community as svc

router = APIRouter(prefix="/community", tags=["community"])


@router.get("/posts", response_model=list[PostSummaryOut])
def list_posts(
    user: Reader,
    db: DbSession,
    category: PostCategory | None = None,
    sort: Literal["latest", "popular"] = "latest",
    limit: int = 30,
    sido: Annotated[str | None, Query(max_length=10)] = None,
    species: Annotated[str | None, Query(max_length=50)] = None,
):
    """글 목록. sido(예: 제주)·species(어종 코드 또는 이름)로 거를 수 있다"""
    return svc.list_posts(db, user, category, sort, limit, sido, species)


@router.post("/posts", response_model=PostDetailOut, status_code=status.HTTP_201_CREATED)
def create_post(data: PostIn, user: CurrentUser, db: DbSession):
    return svc.create_post(db, user, data)


@router.get("/posts/{post_id}", response_model=PostDetailOut)
def get_post(post_id: int, user: Reader, db: DbSession):
    return svc.get_post(db, user, post_id)


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(post_id: int, user: CurrentUser, db: DbSession):
    svc.delete_post(db, user, post_id)


@router.post("/posts/{post_id}/comments", response_model=PostDetailOut, status_code=status.HTTP_201_CREATED)
def add_comment(post_id: int, data: CommentIn, user: CurrentUser, db: DbSession):
    return svc.add_comment(db, user, post_id, data)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: int, user: CurrentUser, db: DbSession):
    svc.delete_comment(db, user, comment_id)


@router.put("/posts/{post_id}/like", response_model=LikeOut)
def like(post_id: int, user: CurrentUser, db: DbSession):
    return svc.set_like(db, user, post_id, True)


@router.delete("/posts/{post_id}/like", response_model=LikeOut)
def unlike(post_id: int, user: CurrentUser, db: DbSession):
    return svc.set_like(db, user, post_id, False)


@router.post("/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def report(data: ReportIn, user: CurrentUser, db: DbSession):
    """신고 (앱스토어 사용자 생성 콘텐츠 정책: 신고 수단 필수). 누적 시 자동 숨김"""
    return svc.report(db, user, data)
