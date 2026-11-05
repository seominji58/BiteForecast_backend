import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import AppUser

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    x_device_id: Annotated[str | None, Header()] = None,
) -> AppUser:
    """X-Device-Id 헤더(UUID)로 사용자 식별. 처음 보는 기기면 사용자 생성 (명세 D-2)"""
    if not x_device_id:
        raise HTTPException(status_code=401, detail="X-Device-Id 헤더가 필요합니다")
    try:
        device_id = str(uuid.UUID(x_device_id))
    except ValueError:
        raise HTTPException(status_code=401, detail="X-Device-Id 형식이 올바르지 않습니다") from None

    user = db.scalar(select(AppUser).where(AppUser.device_id == device_id))
    if user is None:
        user = AppUser(device_id=device_id)
        db.add(user)
        db.commit()
    return user


CurrentUser = Annotated[AppUser, Depends(get_current_user)]
