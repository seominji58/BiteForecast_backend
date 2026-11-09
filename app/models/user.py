from datetime import datetime

from sqlalchemy import ForeignKey, String
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
