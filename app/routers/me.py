from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import PointLedger
from app.schemas.journal import MyPointsOut, PointHistoryItem
from app.schemas.me import MyTitleOut
from app.services.titles import get_my_title, total_points

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/title", response_model=MyTitleOut)
def my_title(user: CurrentUser, db: DbSession):
    return get_my_title(db, user)


@router.get("/points", response_model=MyPointsOut)
def my_points(user: CurrentUser, db: DbSession, limit: int = 50):
    rows = db.scalars(
        select(PointLedger)
        .where(PointLedger.user_id == user.id)
        .order_by(PointLedger.id.desc())
        .limit(min(max(limit, 1), 200))
    ).all()
    return MyPointsOut(
        total_points=total_points(db, user),
        history=[PointHistoryItem.model_validate(r) for r in rows],
    )
