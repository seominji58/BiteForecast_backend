from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.core.geo import haversine_km
from app.models import Favorite, Place, PointLedger, UserSpot
from app.schemas.journal import MyPointsOut, PointHistoryItem
from app.schemas.me import MyTitleOut
from app.schemas.place import PlaceOut
from app.schemas.records import RecordSummaryOut
from app.schemas.spot import NearPlace, SpotIn, SpotOut, SpotPatch
from app.services import records
from app.services.location import location_ctx
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


@router.get("/records/summary", response_model=RecordSummaryOut)
def my_records_summary(user: CurrentUser, db: DbSession):
    """내 낚시 기록 요약: 출조 일수·못 잡은 날·어종별 첫 포획·최대어 (기록 집계, 개인 기록 전체)"""
    return records.summary(db, user)


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


# --- 내 낚시터: 직접 찍은 비공개 포인트 (2026-11-23, 본인만 본다) ---

MAX_SPOTS = 100
NEAR_KM = 30.0  # 이 안의 공식 낚시터를 「해황 기준」으로 붙인다


def _spot_out(spot: UserSpot, places: list[Place]) -> SpotOut:
    best: tuple[float, Place] | None = None
    for p in places:
        d = haversine_km(spot.lat, spot.lon, p.lat, p.lon)
        if best is None or d < best[0]:
            best = (d, p)
    near = (
        NearPlace(id=best[1].id, name=best[1].name, km=round(best[0], 1))
        if best and best[0] <= NEAR_KM
        else None
    )
    return SpotOut(
        id=spot.id,
        name=spot.name,
        lat=spot.lat,
        lon=spot.lon,
        memo=spot.memo,
        created_at=spot.created_at,
        near=near,
    )


def _active_places(db) -> list[Place]:
    """좌표를 믿을 수 있는 활성 낚시터만 (위치 의심·보류 곳은 「해황 기준」으로 붙이지 않는다)"""
    ctx = location_ctx(db)
    bad = ctx.suspects | ctx.holds
    rows = db.scalars(
        select(Place).where(Place.is_active.is_(True), Place.lat.is_not(None), Place.lon.is_not(None))
    )
    return [p for p in rows if p.id not in bad]


def _my_spot(db, user, spot_id: int) -> UserSpot:
    spot = db.get(UserSpot, spot_id)
    if spot is None or spot.user_id != user.id:
        raise HTTPException(status_code=404, detail="포인트를 찾을 수 없습니다")
    return spot


@router.get("/spots", response_model=list[SpotOut])
def my_spots(user: CurrentUser, db: DbSession):
    rows = db.scalars(select(UserSpot).where(UserSpot.user_id == user.id).order_by(UserSpot.id.desc())).all()
    places = _active_places(db)
    return [_spot_out(s, places) for s in rows]


@router.post("/spots", response_model=SpotOut, status_code=status.HTTP_201_CREATED)
def add_spot(body: SpotIn, user: CurrentUser, db: DbSession):
    count = len(db.scalars(select(UserSpot.id).where(UserSpot.user_id == user.id)).all())
    if count >= MAX_SPOTS:
        raise HTTPException(status_code=409, detail=f"포인트는 {MAX_SPOTS}개까지 저장할 수 있어요")
    spot = UserSpot(
        user_id=user.id,
        name=body.name.strip(),
        lat=body.lat,
        lon=body.lon,
        memo=(body.memo or "").strip() or None,
    )
    db.add(spot)
    db.commit()
    return _spot_out(spot, _active_places(db))


@router.patch("/spots/{spot_id}", response_model=SpotOut)
def edit_spot(spot_id: int, body: SpotPatch, user: CurrentUser, db: DbSession):
    spot = _my_spot(db, user, spot_id)
    if body.name is not None:
        spot.name = body.name.strip()
    if "memo" in body.model_fields_set:
        spot.memo = (body.memo or "").strip() or None
    db.commit()
    return _spot_out(spot, _active_places(db))


@router.delete("/spots/{spot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_spot(spot_id: int, user: CurrentUser, db: DbSession):
    db.delete(_my_spot(db, user, spot_id))
    db.commit()
