from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.models import Place, PlaceStation, Region, Species
from app.schemas.journal import SpeciesOut
from app.schemas.place import PlaceDetailOut, PlaceOut, PlaceStationOut, RegionOut

router = APIRouter(tags=["places"])


@router.get("/species", response_model=list[SpeciesOut])
def list_species(db: DbSession):
    return db.scalars(select(Species).order_by(Species.name_ko)).all()


@router.get("/regions", response_model=list[RegionOut])
def list_regions(db: DbSession):
    return db.scalars(select(Region).where(Region.is_active.is_(True)).order_by(Region.id)).all()


@router.get("/places", response_model=list[PlaceOut])
def list_places(db: DbSession, q: str | None = None, region_id: int | None = None):
    """장소 검색 (FR-01). 결과가 비면 앱에서 「지원 지역이 아닙니다」 표시"""
    stmt = select(Place).where(Place.is_active.is_(True))
    if region_id is not None:
        stmt = stmt.where(Place.region_id == region_id)
    if q:
        stmt = stmt.where(Place.name.contains(q.strip()))
    return db.scalars(stmt.order_by(Place.name)).all()


@router.get("/places/{place_id}", response_model=PlaceDetailOut)
def get_place(place_id: int, db: DbSession):
    place = db.scalar(
        select(Place)
        .where(Place.id == place_id)
        .options(selectinload(Place.stations).selectinload(PlaceStation.station))
    )
    if place is None:
        raise HTTPException(status_code=404, detail="장소를 찾을 수 없습니다")

    return PlaceDetailOut(
        **PlaceOut.model_validate(place).model_dump(),
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
