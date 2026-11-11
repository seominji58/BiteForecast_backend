from fastapi import APIRouter, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.models import Place, PlaceInfo, PlaceStation, Region, Species
from app.schemas.journal import SpeciesOut
from app.schemas.place import PlaceDetailOut, PlaceInfoOut, PlaceOut, PlaceStationOut, RegionOut
from app.services.location import location_ctx, place_out

router = APIRouter(tags=["places"])


@router.get("/species", response_model=list[SpeciesOut])
def list_species(db: DbSession):
    return db.scalars(select(Species).order_by(Species.name_ko)).all()


@router.get("/regions", response_model=list[RegionOut])
def list_regions(db: DbSession):
    return db.scalars(select(Region).where(Region.is_active.is_(True)).order_by(Region.name)).all()


@router.get("/places", response_model=list[PlaceOut])
def list_places(db: DbSession, q: str | None = None, region_id: int | None = None):
    """장소 검색 (FR-01): 장소명·지역명·주소에 검색어가 들어간 곳.

    결과가 비면 앱에서 「지원 지역이 아닙니다」 표시
    """
    stmt = (
        select(Place)
        .join(Region)
        .outerjoin(PlaceInfo)
        .where(Place.is_active.is_(True))
        .options(selectinload(Place.region), selectinload(Place.info))
    )
    if region_id is not None:
        stmt = stmt.where(Place.region_id == region_id)
    if q and q.strip():
        term = q.strip()
        stmt = stmt.where(
            or_(Place.name.contains(term), Region.name.contains(term), PlaceInfo.address.contains(term))
        )
    rows = db.scalars(stmt.order_by(Region.name, Place.name)).all()
    ctx = location_ctx(db)  # 위치 판단은 한 번만 읽는다
    return [place_out(db, p, ctx) for p in rows]


@router.get("/places/{place_id}", response_model=PlaceDetailOut)
def get_place(place_id: int, db: DbSession):
    place = db.scalar(
        select(Place)
        .where(Place.id == place_id)
        .options(
            selectinload(Place.region),
            selectinload(Place.info),
            selectinload(Place.stations).selectinload(PlaceStation.station),
        )
    )
    if place is None:
        raise HTTPException(status_code=404, detail="장소를 찾을 수 없습니다")

    return PlaceDetailOut(
        **place_out(db, place).model_dump(),
        info=PlaceInfoOut.model_validate(place.info) if place.info else None,
        stations=[
            PlaceStationOut(
                role=ps.role,
                station_id=ps.station_id,
                station_name=ps.station.name,
                provider=ps.station.provider,
                distance_km=ps.distance_km,
            )
            for ps in place.stations
        ],
    )
