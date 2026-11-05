from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AppUser, PointLedger, Title
from app.schemas.me import MyTitleOut, TitleInfo


def total_points(db: Session, user: AppUser) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(PointLedger.delta), 0)).where(PointLedger.user_id == user.id)
    )


def resolve_title(total: int, titles: Sequence[Title]) -> MyTitleOut:
    """현재 칭호 = min_points ≤ 총점 중 최댓값. 총점이 줄면 강등된다 (FR-12)"""
    ordered = sorted(titles, key=lambda t: t.min_points)
    if not ordered:
        raise ValueError("칭호 기준 데이터가 없습니다")

    current = ordered[0]
    nxt: Title | None = None
    for t in ordered:
        if t.min_points <= total:
            current = t
        else:
            nxt = t
            break

    return MyTitleOut(
        total_points=total,
        current=TitleInfo(name=current.name, min_points=current.min_points),
        next=TitleInfo(name=nxt.name, min_points=nxt.min_points) if nxt else None,
        points_to_next=(nxt.min_points - total) if nxt else None,
    )


def get_my_title(db: Session, user: AppUser) -> MyTitleOut:
    titles = db.scalars(select(Title)).all()
    return resolve_title(total_points(db, user), titles)
