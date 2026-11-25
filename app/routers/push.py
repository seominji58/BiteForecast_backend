"""푸시 알림: 폰 등록·해제, 알림 종류별 켜기·끄기 (2026-11-25). 로그인한 사용자만"""

from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import PushDevice, PushPref
from app.models.base import utcnow

router = APIRouter(prefix="/me/push", tags=["push"])


class DeviceIn(BaseModel):
    token: str = Field(min_length=10, max_length=512)
    platform: Literal["android", "ios"]


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=512)


class PrefsOut(BaseModel):
    fav_good: bool = True
    trip_warning: bool = True
    weekly_best: bool = True


class PrefsIn(BaseModel):
    fav_good: bool | None = None
    trip_warning: bool | None = None
    weekly_best: bool | None = None


@router.put("/device", status_code=status.HTTP_204_NO_CONTENT)
def register_device(body: DeviceIn, user: CurrentUser, db: DbSession):
    """앱을 열 때마다 보낸다. 같은 폰이 다른 계정으로 로그인하면 그 계정으로 옮긴다"""
    dev = db.scalar(select(PushDevice).where(PushDevice.token == body.token))
    if dev is None:
        db.add(PushDevice(user_id=user.id, token=body.token, platform=body.platform, last_seen_at=utcnow()))
    else:
        dev.user_id, dev.platform, dev.last_seen_at = user.id, body.platform, utcnow()
    db.commit()


@router.post("/device/remove", status_code=status.HTTP_204_NO_CONTENT)
def remove_device(body: TokenIn, user: CurrentUser, db: DbSession):
    """로그아웃·알림 끄기: 이 폰에는 더 보내지 않는다"""
    db.query(PushDevice).filter(PushDevice.token == body.token, PushDevice.user_id == user.id).delete()
    db.commit()


@router.get("/prefs", response_model=PrefsOut)
def get_prefs(user: CurrentUser, db: DbSession):
    p = db.get(PushPref, user.id)
    return (
        PrefsOut()
        if p is None
        else PrefsOut(fav_good=p.fav_good, trip_warning=p.trip_warning, weekly_best=p.weekly_best)
    )


@router.patch("/prefs", response_model=PrefsOut)
def set_prefs(body: PrefsIn, user: CurrentUser, db: DbSession):
    p = db.get(PushPref, user.id)
    if p is None:
        p = PushPref(user_id=user.id, fav_good=True, trip_warning=True, weekly_best=True)
        db.add(p)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    return PrefsOut(fav_good=p.fav_good, trip_warning=p.trip_warning, weekly_best=p.weekly_best)
