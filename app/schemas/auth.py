import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# 닉네임: 2~12자, 한글·영문·숫자·밑줄
NICKNAME_RE = re.compile(r"^[0-9A-Za-z가-힣_]{2,12}$")
RESERVED = {"관리자", "운영자", "admin", "administrator", "입질예보"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def check_nickname(v: str) -> str:
    v = v.strip()
    if not NICKNAME_RE.match(v):
        raise ValueError("닉네임은 2~12자의 한글·영문·숫자·밑줄(_)만 쓸 수 있어요")
    if v.lower() in RESERVED:
        raise ValueError("쓸 수 없는 닉네임이에요")
    return v


class Agreements(BaseModel):
    """가입 동의 (필수 3개). 동의 시각은 서버가 기록한다"""

    over_14: bool
    terms: bool
    privacy: bool

    def all_agreed(self) -> bool:
        return self.over_14 and self.terms and self.privacy


class SignupIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=72)
    nickname: str
    agreements: Agreements

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("이메일 형식이 올바르지 않아요")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("비밀번호는 영문과 숫자를 섞어 8자 이상으로 만들어 주세요")
        return v

    @field_validator("nickname")
    @classmethod
    def _nickname(cls, v: str) -> str:
        return check_nickname(v)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=72)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.strip().lower()


class GoogleIn(BaseModel):
    id_token: str = Field(min_length=20, max_length=4096)


class SocialIn(BaseModel):
    """소셜 로그인: 제공자가 준 토큰(구글·카카오는 ID 토큰) + 서버가 낸 nonce(카카오 필수)"""

    token: str = Field(min_length=20, max_length=8192)
    nonce: str | None = Field(default=None, max_length=200)


class SocialSignupIn(SocialIn):
    nickname: str
    agreements: Agreements

    @field_validator("nickname")
    @classmethod
    def _nickname(cls, v: str) -> str:
        return check_nickname(v)


class GoogleSignupIn(GoogleIn):
    nickname: str
    agreements: Agreements

    @field_validator("nickname")
    @classmethod
    def _nickname(cls, v: str) -> str:
        return check_nickname(v)


class NicknameIn(BaseModel):
    nickname: str

    @field_validator("nickname")
    @classmethod
    def _nickname(cls, v: str) -> str:
        return check_nickname(v)


class AccountOut(BaseModel):
    id: int
    nickname: str
    email: str | None
    provider: Literal["email", "google", "kakao"]  # 대표 로그인 수단
    providers: list[str] = []  # 연결된 로그인 수단 전부
    created_at: datetime


class MergeInfo(BaseModel):
    """이 기기에서 로그인 없이 만든 기록을 계정으로 옮길 수 있는지"""

    done: bool  # 이번 로그인에서 자동으로 옮겼는지
    available: bool  # 옮길 수 있는 기록이 남아 있는지 (앱이 사용자에게 묻는다)
    journals: int
    posts: int


class AuthOut(BaseModel):
    status: Literal["ok"] = "ok"
    token: str
    expires_at: datetime
    account: AccountOut
    merge: MergeInfo


class GoogleSignupNeeded(BaseModel):
    """처음 보는 구글 계정: 닉네임·약관 동의를 받아 /auth/google/signup 으로 다시 보낸다"""

    status: Literal["signup_required"] = "signup_required"
    email: str | None
    name: str | None


class NicknameCheckOut(BaseModel):
    available: bool
    message: str | None = None


class SignupNeeded(BaseModel):
    """처음 보는 소셜 계정: 닉네임·약관 동의를 받아 /auth/social/{provider}/signup 으로 다시 보낸다"""

    status: Literal["signup_required"] = "signup_required"
    provider: str
    email: str | None
    name: str | None


class NonceOut(BaseModel):
    nonce: str
    expires_in: int  # 초
