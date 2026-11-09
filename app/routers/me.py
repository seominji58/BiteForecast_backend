from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models import Favorite, Place, PointLedger
from app.schemas.journal import MyPointsOut, PointHistoryItem
from app.schemas.me import MyTitleOut
from app.schemas.place import PlaceOut
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


# --- 즐겨찾기 낚시터 (로그인 필요, 기기를 바꿔도 유지) ---


@router.get("/favorites", response_model=list[PlaceOut])
def my_favorites(user: CurrentUser, db: DbSession):
    rows = db.scalars(
        select(Place)
        .join(Favorite, Favorite.place_id == Place.id)
        .where(Favorite.user_id == user.id, Place.is_active.is_(True))
        .order_by(Favorite.created_at.desc())
        .options(selectinload(Place.region), selectinload(Place.info))
    ).all()
    return rows


@router.put("/favorites/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_favorite(place_id: int, user: CurrentUser, db: DbSession):
    place = db.get(Place, place_id)
    if place is None or not place.is_active:
        raise HTTPException(status_code=404, detail="낚시터를 찾을 수 없습니다")
    if db.get(Favorite, (user.id, place_id)) is None:
        db.add(Favorite(user_id=user.id, place_id=place_id))
        db.commit()


@router.delete("/favorites/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(place_id: int, user: CurrentUser, db: DbSession):
    fav = db.get(Favorite, (user.id, place_id))
    if fav is not None:
        db.delete(fav)
        db.commit()
