from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, Reader
from app.models.community import PostCategory
from app.schemas.community import (
    BlockIn,
    BlockOut,
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
    place_id: int | None = None,
    before_id: int | None = None,
):
    """글 목록. sido(예: 제주)·species(어종 코드 또는 이름)·place_id(낚시터)로 거를 수 있다

    - place_id: 낚시터 이름까지 공개한 글만 (지역만·숨김 글은 낚시터로 찾을 수 없다)
    - before_id: 최신순에서 「더 보기」 — 이 글보다 앞선 글
    """
    return svc.list_posts(db, user, category, sort, limit, sido, species, place_id, before_id)


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


@router.post("/blocks", response_model=BlockOut, status_code=status.HTTP_201_CREATED)
def block(data: BlockIn, user: CurrentUser, db: DbSession):
    """이 글·댓글 작성자를 차단: 내 화면에서 그 사람의 글·댓글이 보이지 않는다 (상대에게 알리지 않음)"""
    return svc.block(db, user, data)


@router.get("/blocks", response_model=list[BlockOut])
def list_blocks(user: CurrentUser, db: DbSession):
    return svc.list_blocks(db, user)


@router.delete("/blocks/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def unblock(user_id: int, user: CurrentUser, db: DbSession):
    svc.unblock(db, user, user_id)
