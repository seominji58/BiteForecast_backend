"""출조계획 API (로그인 필요, 본인 것만)"""

from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import Field

from app.api.deps import CurrentUser, DbSession
from app.schemas.trip import (
    MAX_CHECKLIST,
    ChecklistItemIn,
    TripIn,
    TripListItemOut,
    TripOut,
    TripOutlookOut,
    TripPatch,
    TripStopIn,
    TripStopPatch,
)
from app.services import trips as svc

router = APIRouter(prefix="/me/trips", tags=["trips"])


@router.get("", response_model=list[TripListItemOut])
def list_trips(user: CurrentUser, db: DbSession, when: Literal["upcoming", "past"] = "upcoming"):
    return svc.list_trips(db, user, when)


@router.post("", response_model=TripOut, status_code=status.HTTP_201_CREATED)
def create_trip(data: TripIn, user: CurrentUser, db: DbSession):
    return svc.create_trip(db, user, data)


@router.get("/{trip_id}", response_model=TripOut)
def get_trip(trip_id: int, user: CurrentUser, db: DbSession):
    return svc.get_trip(db, user, trip_id)


@router.patch("/{trip_id}", response_model=TripOut)
def update_trip(trip_id: int, data: TripPatch, user: CurrentUser, db: DbSession):
    return svc.update_trip(db, user, trip_id, data)


@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trip(trip_id: int, user: CurrentUser, db: DbSession):
    svc.delete_trip(db, user, trip_id)


@router.post("/{trip_id}/stops", response_model=TripOut, status_code=status.HTTP_201_CREATED)
def add_stop(trip_id: int, data: TripStopIn, user: CurrentUser, db: DbSession):
    return svc.add_stop(db, user, trip_id, data)


@router.patch("/{trip_id}/stops/{stop_id}", response_model=TripOut)
def update_stop(trip_id: int, stop_id: int, data: TripStopPatch, user: CurrentUser, db: DbSession):
    return svc.update_stop(db, user, trip_id, stop_id, data)


@router.delete("/{trip_id}/stops/{stop_id}", response_model=TripOut)
def delete_stop(trip_id: int, stop_id: int, user: CurrentUser, db: DbSession):
    return svc.delete_stop(db, user, trip_id, stop_id)


@router.put("/{trip_id}/checklist", response_model=TripOut)
def replace_checklist(
    trip_id: int,
    items: Annotated[list[ChecklistItemIn], Field(max_length=MAX_CHECKLIST)],
    user: CurrentUser,
    db: DbSession,
):
    return svc.replace_checklist(db, user, trip_id, items)


@router.get("/{trip_id}/outlook", response_model=TripOutlookOut)
def outlook(trip_id: int, user: CurrentUser, db: DbSession):
    return svc.outlook(db, user, trip_id)
