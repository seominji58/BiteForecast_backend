from typing import Annotated

from fastapi import APIRouter, Header, Query, status

from app.api.deps import CurrentAccount, DbSession, DeviceId
from app.schemas.auth import (
    AccountOut,
    AuthOut,
    GoogleIn,
    GoogleSignupIn,
    GoogleSignupNeeded,
    LoginIn,
    MergeInfo,
    NicknameCheckOut,
    NicknameIn,
    SignupIn,
    check_nickname,
)
from app.services import auth as svc

router = APIRouter(tags=["auth"])


@router.post("/auth/signup", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
def signup(data: SignupIn, db: DbSession, device_id: DeviceId = None):
    """이메일 회원가입. 이 기기에서 로그인 없이 쓰던 기록은 새 계정에 그대로 이어진다"""
    return svc.signup_email(db, data.email, data.password, data.nickname, data.agreements, device_id)


@router.post("/auth/login", response_model=AuthOut)
def login(data: LoginIn, db: DbSession, device_id: DeviceId = None):
    return svc.login_email(db, data.email, data.password, device_id)


@router.post("/auth/google", response_model=AuthOut | GoogleSignupNeeded)
def google(data: GoogleIn, db: DbSession, device_id: DeviceId = None):
    """구글 로그인. 처음 보는 구글 계정이면 status=signup_required

    → 닉네임·약관 동의를 받아 /auth/google/signup 으로 다시 보낸다
    """
    return svc.login_google(db, data.id_token, device_id)


@router.post("/auth/google/signup", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
def google_signup(data: GoogleSignupIn, db: DbSession, device_id: DeviceId = None):
    return svc.signup_google(db, data.id_token, data.nickname, data.agreements, device_id)


@router.get("/auth/config")
def auth_config():
    """앱이 어떤 로그인 버튼을 보여줄지 (구글 클라이언트 ID 가 설정됐는지)"""
    return {"google": bool(svc.google_client_ids()), "email": True}


@router.get("/auth/nickname-check", response_model=NicknameCheckOut)
def nickname_check(db: DbSession, nickname: Annotated[str, Query(max_length=40)]):
    try:
        nickname = check_nickname(nickname)
    except ValueError as e:
        return NicknameCheckOut(available=False, message=str(e))
    if svc.nickname_taken(db, nickname):
        return NicknameCheckOut(available=False, message="이미 쓰고 있는 닉네임이에요")
    return NicknameCheckOut(available=True)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(_: CurrentAccount, db: DbSession, authorization: Annotated[str | None, Header()] = None):
    svc.revoke_session(db, (authorization or "")[7:].strip())


@router.post("/auth/merge-device", response_model=MergeInfo)
def merge_device(account: CurrentAccount, db: DbSession, device_id: DeviceId = None):
    """이 기기에서 로그인 없이 쓴 기록·글을 로그인한 계정으로 옮긴다 (사용자가 동의했을 때)"""
    return svc.merge_device(db, account, device_id)


@router.get("/me/account", response_model=AccountOut)
def my_account(account: CurrentAccount):
    return svc.account_out(account)


@router.patch("/me/account", response_model=AccountOut)
def update_account(data: NicknameIn, account: CurrentAccount, db: DbSession):
    return svc.change_nickname(db, account, data.nickname)


@router.delete("/me/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account: CurrentAccount, db: DbSession):
    """회원 탈퇴 (기록·사진·글·댓글·포인트 삭제). 되돌릴 수 없다"""
    svc.delete_account(db, account)
