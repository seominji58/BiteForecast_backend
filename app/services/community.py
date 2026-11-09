"""커뮤니티 (명세 §15, v1.3).

운영 원칙
- 로그인 없이 기기 사용자로 작성. 표시명은 「낚시인{번호}」 + 현재 칭호
- 신고 3회(설정값) 누적 시 자동 숨김. 작성자 본인은 자기 글을 계속 볼 수 있다
- 삭제는 소프트 삭제 (작성자 본인만)
- 위치는 사용자가 고른 지원 장소만 연결 (GPS 사용 안 함, NFR-01)
"""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Account, AppUser, Journal, Photo, Place, PointLedger, Species, Title
from app.models.base import utcnow
from app.models.community import Comment, ContentReport, Post, PostCategory, PostLike, ReportTarget
from app.models.enums import PhotoPurpose, VerificationStatus
from app.schemas.community import (
    AuthorOut,
    CatchOut,
    CommentIn,
    CommentOut,
    LikeOut,
    PostDetailOut,
    PostIn,
    PostSummaryOut,
    ReportIn,
    ReportOut,
)
from app.services import photos
from app.services.titles import resolve_title


def species_name(db: Session, code: str | None, etc: str | None) -> str | None:
    if code:
        sp = db.get(Species, code)
        return sp.name_ko if sp else code
    return etc


EXCERPT_LEN = 80
POPULAR_WINDOW = timedelta(days=30)


def nickname(user_id: int) -> str:
    """로그인 없이 쓰던 사용자 표시명"""
    return f"낚시인{user_id:04d}"


def nicknames(db: Session, user_ids: set[int]) -> dict[int, str]:
    """작성자 표시명: 계정 닉네임, 계정이 없으면 「낚시인0012」"""
    names = dict(
        db.execute(select(Account.user_id, Account.nickname).where(Account.user_id.in_(user_ids))).all()
    )
    return {uid: names.get(uid) or nickname(uid) for uid in user_ids}


def _authors(db: Session, user_ids: set[int]) -> dict[int, AuthorOut]:
    titles = db.scalars(select(Title)).all()
    totals = dict(
        db.execute(
            select(PointLedger.user_id, func.coalesce(func.sum(PointLedger.delta), 0))
            .where(PointLedger.user_id.in_(user_ids))
            .group_by(PointLedger.user_id)
        ).all()
    )
    names = nicknames(db, user_ids)
    return {
        uid: AuthorOut(nickname=names[uid], title=resolve_title(totals.get(uid, 0), titles).current.name)
        for uid in user_ids
    }


def _visible_posts(user: AppUser):
    """삭제되지 않았고, 숨김이 아니거나 내 글"""
    return select(Post).where(Post.deleted_at.is_(None), (Post.hidden.is_(False)) | (Post.user_id == user.id))


def _counts(db: Session, post_ids: list[int]) -> tuple[dict[int, int], dict[int, int]]:
    if not post_ids:
        return {}, {}
    likes = dict(
        db.execute(
            select(PostLike.post_id, func.count())
            .where(PostLike.post_id.in_(post_ids))
            .group_by(PostLike.post_id)
        ).all()
    )
    comments = dict(
        db.execute(
            select(Comment.post_id, func.count())
            .where(Comment.post_id.in_(post_ids), Comment.deleted_at.is_(None), Comment.hidden.is_(False))
            .group_by(Comment.post_id)
        ).all()
    )
    return likes, comments


def _summaries(db: Session, user: AppUser, posts: list[Post]) -> list[PostSummaryOut]:
    ids = [p.id for p in posts]
    likes, comments = _counts(db, ids)
    liked = set(
        db.scalars(
            select(PostLike.post_id).where(PostLike.user_id == user.id, PostLike.post_id.in_(ids))
        ).all()
    )
    authors = _authors(db, {p.user_id for p in posts})
    places = {
        p.id: p.name
        for p in db.scalars(select(Place).where(Place.id.in_({x.place_id for x in posts if x.place_id})))
    }
    species = {
        s.code: s.name_ko
        for s in db.scalars(
            select(Species).where(Species.code.in_({x.species_code for x in posts if x.species_code}))
        )
    }
    popular_min = get_settings().community_popular_likes
    out = []
    for p in posts:
        body = " ".join(p.body.split())
        pics = _post_photos(db, p)
        out.append(
            PostSummaryOut(
                id=p.id,
                category=p.category,
                title=p.title,
                excerpt=body[:EXCERPT_LEN] + ("…" if len(body) > EXCERPT_LEN else ""),
                author=authors[p.user_id],
                place_name=places.get(p.place_id) if p.place_id else None,
                species_name=species.get(p.species_code) if p.species_code else p.species_etc,
                like_count=likes.get(p.id, 0),
                comment_count=comments.get(p.id, 0),
                liked=p.id in liked,
                mine=p.user_id == user.id,
                popular=likes.get(p.id, 0) >= popular_min,
                created_at=p.created_at,
                verified=_verified_journal(db, p) is not None,
                photo_count=len(pics),
                thumb=photos.photo_out(pics[0]) if pics else None,
            )
        )
    return out


def _verified_journal(db: Session, p: Post) -> Journal | None:
    """공유된 일지가 지금도 인증 완료 상태일 때만 (반려·삭제되면 배지가 빠진다)"""
    if p.journal_id is None:
        return None
    j = db.get(Journal, p.journal_id)
    if j is None or j.deleted_at is not None or j.verification_status != VerificationStatus.APPROVED:
        return None
    return j


def _post_photos(db: Session, p: Post) -> list[Photo]:
    """글 사진: 일지 공유 글이면 (인증 완료 상태일 때) 일지 사진, 아니면 글에 올린 사진"""
    j = _verified_journal(db, p)
    if j is not None:
        cond = Photo.journal_id == j.id
    elif p.journal_id is not None:
        return []
    else:
        cond = Photo.post_id == p.id
    return list(
        db.scalars(select(Photo).where(cond, Photo.deleted_at.is_(None)).order_by(Photo.sort_order, Photo.id))
    )


def list_posts(
    db: Session, user: AppUser, category: PostCategory | None, sort: str, limit: int
) -> list[PostSummaryOut]:
    stmt = _visible_posts(user)
    if category is not None:
        stmt = stmt.where(Post.category == category)
    limit = min(max(limit, 1), 100)

    if sort == "popular":
        # 최근 30일 글 중 좋아요+댓글 많은 순
        stmt = stmt.where(Post.created_at >= utcnow() - POPULAR_WINDOW)
        posts = list(db.scalars(stmt).all())
        likes, comments = _counts(db, [p.id for p in posts])
        posts.sort(key=lambda p: (likes.get(p.id, 0) + comments.get(p.id, 0), p.created_at), reverse=True)
        posts = posts[:limit]
    else:
        posts = list(db.scalars(stmt.order_by(Post.created_at.desc(), Post.id.desc()).limit(limit)).all())
    return _summaries(db, user, posts)


def _get_post(db: Session, user: AppUser, post_id: int) -> Post:
    p = db.scalar(_visible_posts(user).where(Post.id == post_id))
    if p is None:
        raise HTTPException(status_code=404, detail="글을 찾을 수 없습니다")
    return p


def get_post(db: Session, user: AppUser, post_id: int) -> PostDetailOut:
    p = _get_post(db, user, post_id)
    summary = _summaries(db, user, [p])[0]
    comments = db.scalars(
        select(Comment)
        .where(
            Comment.post_id == p.id,
            Comment.deleted_at.is_(None),
            (Comment.hidden.is_(False)) | (Comment.user_id == user.id),
        )
        .order_by(Comment.created_at, Comment.id)
    ).all()
    authors = _authors(db, {c.user_id for c in comments}) if comments else {}
    j = _verified_journal(db, p)
    return PostDetailOut(
        **summary.model_dump(),
        body=p.body,
        photos=[photos.photo_out(x) for x in _post_photos(db, p)],
        catch=CatchOut(
            fished_at=j.fished_at,
            species_name=species_name(db, j.species_code, j.species_etc),
            count=j.count,
            max_length_cm=j.max_length_cm,
        )
        if j is not None
        else None,
        comments=[
            CommentOut(
                id=c.id,
                body=c.body,
                author=authors[c.user_id],
                mine=c.user_id == user.id,
                created_at=c.created_at,
            )
            for c in comments
        ],
    )


def create_post(db: Session, user: AppUser, data: PostIn) -> PostDetailOut:
    values = data.model_dump(exclude={"photo_ids", "journal_id"})
    if data.journal_id is not None:
        # 인증 완료된 내 일지 공유: 조황공유 글, 장소·어종·사진은 일지 것을 그대로 쓴다 (포인트 지급 없음)
        j = db.get(Journal, data.journal_id)
        if j is None or j.user_id != user.id or j.deleted_at is not None:
            raise HTTPException(status_code=404, detail="공유할 기록을 찾을 수 없습니다")
        if j.verification_status != VerificationStatus.APPROVED:
            raise HTTPException(
                status_code=400, detail="인증이 완료된 기록만 「인증 조황」으로 공유할 수 있습니다"
            )
        if db.scalar(select(Post.id).where(Post.journal_id == j.id, Post.deleted_at.is_(None))):
            raise HTTPException(status_code=409, detail="이미 커뮤니티에 공유한 기록입니다")
        if data.photo_ids:
            raise HTTPException(status_code=400, detail="기록 공유 글에는 기록의 사진이 그대로 붙습니다")
        values.update(
            category=PostCategory.CATCH,
            place_id=j.place_id,
            species_code=j.species_code,
            species_etc=j.species_etc,
            journal_id=j.id,
        )
    else:
        if data.place_id is not None:
            place = db.get(Place, data.place_id)
            if place is None or not place.is_active:
                raise HTTPException(status_code=400, detail="지원하지 않는 장소입니다")
        if data.species_code and db.get(Species, data.species_code) is None:
            raise HTTPException(status_code=400, detail="알 수 없는 어종 코드입니다")
    p = Post(user_id=user.id, **values)
    db.add(p)
    db.flush()
    if data.journal_id is None:
        photos.attach(db, user, data.photo_ids, PhotoPurpose.POST, post=p)
    db.commit()
    return get_post(db, user, p.id)


def delete_post(db: Session, user: AppUser, post_id: int) -> None:
    p = _get_post(db, user, post_id)
    if p.user_id != user.id:
        raise HTTPException(status_code=403, detail="내가 쓴 글만 삭제할 수 있습니다")
    p.deleted_at = utcnow()
    photos.delete_for(db, post=p)  # 글에 올린 사진만 삭제 (공유한 일지 사진은 일지에 남는다)
    db.commit()


def add_comment(db: Session, user: AppUser, post_id: int, data: CommentIn) -> PostDetailOut:
    p = _get_post(db, user, post_id)
    db.add(Comment(post_id=p.id, user_id=user.id, body=data.body))
    db.commit()
    return get_post(db, user, p.id)


def delete_comment(db: Session, user: AppUser, comment_id: int) -> None:
    c = db.get(Comment, comment_id)
    if c is None or c.deleted_at is not None:
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다")
    if c.user_id != user.id:
        raise HTTPException(status_code=403, detail="내가 쓴 댓글만 삭제할 수 있습니다")
    c.deleted_at = utcnow()
    db.commit()


def set_like(db: Session, user: AppUser, post_id: int, liked: bool) -> LikeOut:
    p = _get_post(db, user, post_id)
    existing = db.get(PostLike, (p.id, user.id))
    if liked and existing is None:
        db.add(PostLike(post_id=p.id, user_id=user.id))
    elif not liked and existing is not None:
        db.delete(existing)
    db.commit()
    count = db.scalar(select(func.count()).select_from(PostLike).where(PostLike.post_id == p.id))
    return LikeOut(liked=liked, like_count=count)


def report(db: Session, user: AppUser, data: ReportIn) -> ReportOut:
    model = Post if data.target_type == ReportTarget.POST else Comment
    target = db.get(model, data.target_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(status_code=404, detail="신고할 대상을 찾을 수 없습니다")
    if target.user_id == user.id:
        raise HTTPException(status_code=400, detail="내가 쓴 글은 신고할 수 없습니다")

    db.add(
        ContentReport(
            target_type=data.target_type, target_id=data.target_id, user_id=user.id, reason=data.reason
        )
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return ReportOut(status="already_reported", hidden=target.hidden)

    n = db.scalar(
        select(func.count())
        .select_from(ContentReport)
        .where(ContentReport.target_type == data.target_type, ContentReport.target_id == data.target_id)
    )
    newly_hidden = False
    if n >= get_settings().community_hide_reports and not target.hidden:
        target.hidden = True
        newly_hidden = True
    db.commit()
    return ReportOut(status="received", hidden=newly_hidden)
