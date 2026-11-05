import hmac
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
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


def get_optional_user(
    db: DbSession,
    x_device_id: Annotated[str | None, Header()] = None,
) -> AppUser | None:
    """사진 보기처럼 기기 ID 없이도 요청할 수 있는 곳용. 처음 보는 기기여도 사용자를 만들지 않는다"""
    if not x_device_id:
        return None
    try:
        device_id = str(uuid.UUID(x_device_id))
    except ValueError:
        return None
    return db.scalar(select(AppUser).where(AppUser.device_id == device_id))


OptionalUser = Annotated[AppUser | None, Depends(get_optional_user)]


def is_admin_token(token: str | None) -> bool:
    expected = get_settings().admin_token
    return bool(expected) and bool(token) and hmac.compare_digest(token.encode(), expected.encode())


def require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    """관리자 검토 API 보호. ADMIN_TOKEN 이 설정되지 않았으면 전부 막는다"""
    if not get_settings().admin_token:
        raise HTTPException(status_code=403, detail="관리자 검토가 설정되지 않았습니다 (ADMIN_TOKEN)")
    if not is_admin_token(x_admin_token):
        raise HTTPException(status_code=401, detail="관리자 토큰이 올바르지 않습니다")


AdminOnly = Depends(require_admin)
