"""출조계획 API (로그인 필요). 만든 사람: 모든 기능 · 함께 가는 참여자: 보기·준비물 체크·담당·내 참여 상태"""

from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import Field

from app.api.deps import CurrentUser, DbSession
from app.schemas.trip import (
    MAX_CHECKLIST,
    ChecklistItemIn,
    ChecklistItemPatch,
    InviteOut,
    InvitePreviewOut,
    MemberStatusIn,
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
invites = APIRouter(prefix="/trip-invites", tags=["trips"])


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


@router.patch("/{trip_id}/checklist/{item_id}", response_model=TripOut)
def patch_checklist_item(
    trip_id: int, item_id: int, data: ChecklistItemPatch, user: CurrentUser, db: DbSession
):
    """준비물 하나 체크·담당 (참여자도 가능)"""
    return svc.patch_checklist_item(db, user, trip_id, item_id, data)


# --- 함께 가기 ---


@router.post("/{trip_id}/invite", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def create_invite(trip_id: int, user: CurrentUser, db: DbSession):
    """초대 코드 만들기 (만든 사람만, 쓸 수 있는 코드가 있으면 그대로)"""
    return svc.create_invite(db, user, trip_id)


@router.delete("/{trip_id}/invite", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(trip_id: int, user: CurrentUser, db: DbSession):
    svc.revoke_invite(db, user, trip_id)


@router.patch("/{trip_id}/members/me", response_model=TripOut)
def set_my_status(trip_id: int, data: MemberStatusIn, user: CurrentUser, db: DbSession):
    """내 참여 상태 (참여·미정·불참)"""
    return svc.set_my_status(db, user, trip_id, data.status)


@router.delete("/{trip_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(trip_id: int, member_user_id: int, user: CurrentUser, db: DbSession):
    """만든 사람은 참여자를 내보내고, 참여자는 스스로 나간다"""
    svc.remove_member(db, user, trip_id, member_user_id)


@invites.get("/{code}", response_model=InvitePreviewOut)
def preview_invite(code: str, user: CurrentUser, db: DbSession):
    """초대 코드로 계획 미리 보기 (로그인 필요)"""
    return svc.preview_invite(db, user, code)


@invites.post("/{code}/join", response_model=TripOut)
def join_trip(code: str, user: CurrentUser, db: DbSession):
    return svc.join_trip(db, user, code)
