from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime


class AppUser(TimestampMixin, Base):
    """데이터의 주인 (기록·사진·글·포인트가 이 ID 에 붙는다).

    로그인 전에는 기기 UUID 로 만들어지고(명세 D-2), 회원가입하면 Account 가 이 사용자에 연결된다.
    계정으로 새로 만든 사용자는 device_id 에 임의 UUID 를 넣는다 (특정 기기와 무관).
    """

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # 개발·검증용 사용자. 이 사용자의 글·사진은 일반 화면에서 숨긴다 (SHOW_TEST_DATA=true 면 보임)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    account: Mapped["Account | None"] = relationship(back_populates="user", uselist=False)


class Account(TimestampMixin, Base):
    """로그인 계정 (이메일 가입 또는 구글). AppUser 와 1:1"""

    __tablename__ = "account"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), unique=True)
    # 로그인 이메일 (소문자 정규화). 탈퇴하면 비워서 같은 이메일로 다시 가입할 수 있게 한다
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # 이메일 가입만
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)  # 구글 계정 고유 ID
    nickname: Mapped[str] = mapped_column(String(20), unique=True)
    nickname_key: Mapped[str] = mapped_column(
        String(20), unique=True, index=True
    )  # 대소문자 무시 중복 확인용
    terms_agreed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    privacy_agreed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    user: Mapped[AppUser] = relationship(back_populates="account")
    identities: Mapped[list["AccountIdentity"]] = relationship(lazy="selectin")


class AccountIdentity(TimestampMixin, Base):
    """소셜 로그인 수단 (구글·카카오, 이후 네이버). 한 계정에 제공자별로 하나씩 붙는다.
    이메일 로그인은 account.email·password_hash 를 그대로 쓴다 (이 표에 넣지 않음)"""

    __tablename__ = "account_identity"
    __table_args__ = (UniqueConstraint("provider", "subject"), UniqueConstraint("account_id", "provider"))

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))  # google | kakao | naver
    subject: Mapped[str] = mapped_column(String(128))  # 제공자가 주는 사용자 고유 ID
    email: Mapped[str | None] = mapped_column(String(254))  # 제공자가 확인됨으로 준 이메일만
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AuthSession(TimestampMixin, Base):
    """로그인 세션. 앱에는 임의 토큰을 주고 DB 에는 해시만 저장한다 (유출돼도 토큰 복원 불가)"""

    __tablename__ = "auth_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Favorite(TimestampMixin, Base):
    __tablename__ = "favorite"

    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"), primary_key=True)


class UserSpot(TimestampMixin, Base):
    """내 낚시터 — 사용자가 지도에 직접 찍은 비공개 포인트 (2026-11-23). 본인만 본다"""

    __tablename__ = "user_spot"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    memo: Mapped[str | None] = mapped_column(String(500))
