import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models import Account, AppUser
from app.services.auth import resolve_session

DbSession = Annotated[Session, Depends(get_db)]

# 로그인하지 않은 사람 (읽기 전용). DB 에 없는 임시 객체라 id 0 은 어떤 글·기록과도 일치하지 않는다
GUEST_ID = 0


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def get_account(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> Account | None:
    token = _bearer(authorization)
    return resolve_session(db, token) if token else None


OptionalAccount = Annotated[Account | None, Depends(get_account)]


def require_account(account: OptionalAccount) -> Account:
    if account is None:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요해요",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return account


CurrentAccount = Annotated[Account, Depends(require_account)]


def get_current_user(account: CurrentAccount) -> AppUser:
    """쓰기(기록·사진·글·댓글·좋아요·신고·포인트)는 로그인 필요 (2026-11-09 결정)"""
    return account.user


CurrentUser = Annotated[AppUser, Depends(get_current_user)]


def get_optional_user(account: OptionalAccount) -> AppUser | None:
    return account.user if account is not None else None


OptionalUser = Annotated[AppUser | None, Depends(get_optional_user)]


def get_reader(account: OptionalAccount) -> AppUser:
    """읽기 전용 화면용: 로그인했으면 그 사용자, 아니면 임시 손님 (liked·mine 은 항상 false)"""
    return account.user if account is not None else AppUser(id=GUEST_ID, device_id="guest")


Reader = Annotated[AppUser, Depends(get_reader)]

# 로그인 없이 쓰던 기기 기록을 계정으로 옮길 때만 쓴다
DeviceId = Annotated[str | None, Header(alias="X-Device-Id")]


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
