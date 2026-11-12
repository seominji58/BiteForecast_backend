"""회원가입·로그인 (이메일 / 구글), 세션, 기기 데이터 이전, 탈퇴.

원칙
- 데이터의 주인은 AppUser. 계정(Account)은 AppUser 에 1:1 로 붙는다
- 처음 가입하면 이 기기의 사용자(로그인 없이 쓰던 기록)에 계정을 그대로 연결한다 → 기록 이전이 필요 없다
- 다른 기기에서 로그인하면 그 기기에서 쓴 기록을 계정으로 옮긴다
  (계정에 기록이 없으면 자동, 있으면 앱이 사용자에게 묻고 /auth/merge-device 로 옮긴다)
- 비밀번호는 scrypt 해시만 저장, 세션 토큰은 SHA-256 해시만 저장
- 탈퇴하면 기록·사진·글·댓글·포인트를 지우고 이메일·구글 연결을 끊는다 (앱스토어 5.1.1 계정 삭제)
"""

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

import jwt
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Account,
    AppUser,
    AuthSession,
    Comment,
    ContentReport,
    Favorite,
    Journal,
    Photo,
    PointLedger,
    Post,
    PostLike,
    TripChecklistItem,
    TripInvite,
    TripMember,
    TripPlan,
    TripStop,
)
from app.models.base import utcnow
from app.schemas.auth import AccountOut, Agreements, AuthOut, GoogleSignupNeeded, MergeInfo
from app.services import photos

# --- 비밀번호 (표준 라이브러리 scrypt) ---
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(dk)}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        algo, n, r, p, salt, dk = (stored or "").split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


# 로그인 실패 제한: 같은 이메일 10분 안에 5번 틀리면 잠시 막는다 (서버 1대 기준 메모리)
_FAILS: dict[str, list[float]] = defaultdict(list)
_FAIL_WINDOW, _FAIL_MAX = 600, 5


def _check_rate(email: str) -> None:
    now = time.monotonic()
    _FAILS[email] = [t for t in _FAILS[email] if now - t < _FAIL_WINDOW]
    if len(_FAILS[email]) >= _FAIL_MAX:
        raise HTTPException(status_code=429, detail="로그인 시도가 많아요. 10분 뒤에 다시 시도해 주세요")


# --- 구글 ID 토큰 검증 ---
_GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISS = ["accounts.google.com", "https://accounts.google.com"]
_jwks: jwt.PyJWKClient | None = None


def google_client_ids() -> list[str]:
    return [x.strip() for x in get_settings().google_client_ids.split(",") if x.strip()]


def verify_google_token(token: str) -> dict:
    """구글이 서명한 ID 토큰인지, 우리 앱(클라이언트 ID)용인지 확인하고 내용을 돌려준다"""
    global _jwks
    audiences = google_client_ids()
    if not audiences:
        raise HTTPException(
            status_code=503, detail="구글 로그인이 아직 설정되지 않았어요 (GOOGLE_CLIENT_IDS)"
        )
    try:
        if _jwks is None:
            _jwks = jwt.PyJWKClient(_GOOGLE_CERTS, cache_keys=True, lifespan=3600)
        key = _jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=audiences, issuer=_GOOGLE_ISS)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401, detail="구글 로그인 정보를 확인하지 못했어요. 다시 시도해 주세요"
        ) from None
    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="구글 계정 정보가 없어요")
    return claims


# --- 세션 ---


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(db: Session, account: Account) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(days=get_settings().session_days)
    db.add(AuthSession(account_id=account.id, token_hash=_hash_token(token), expires_at=expires))
    return token, expires


def resolve_session(db: Session, token: str) -> Account | None:
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
    now = utcnow()
    if s is None or s.revoked_at is not None or s.expires_at <= now:
        return None
    account = db.get(Account, s.account_id)
    if account is None or account.deleted_at is not None:
        return None
    # 쓰면 쓸수록 연장 (하루에 한 번만 기록)
    if s.last_used_at is None or now - s.last_used_at > timedelta(days=1):
        s.last_used_at = now
        s.expires_at = now + timedelta(days=get_settings().session_days)
        db.commit()
    return account


def revoke_session(db: Session, token: str) -> None:
    db.execute(
        update(AuthSession).where(AuthSession.token_hash == _hash_token(token)).values(revoked_at=utcnow())
    )
    db.commit()


# --- 공통 ---


def account_out(a: Account) -> AccountOut:
    return AccountOut(
        id=a.id,
        nickname=a.nickname,
        email=a.email,
        provider="google" if a.google_sub else "email",
        created_at=a.created_at,
    )


def nickname_taken(db: Session, nickname: str, exclude_id: int | None = None) -> bool:
    stmt = select(Account.id).where(Account.nickname_key == nickname.lower())
    if exclude_id is not None:
        stmt = stmt.where(Account.id != exclude_id)
    return db.scalar(stmt) is not None


def _device_user(db: Session, device_id: str | None) -> AppUser | None:
    """로그인 없이 쓰던 이 기기의 사용자 (계정이 없고 탈퇴하지 않은 경우만)"""
    if not device_id:
        return None
    try:
        device_id = str(uuid.UUID(device_id))
    except ValueError:
        return None
    u = db.scalar(select(AppUser).where(AppUser.device_id == device_id, AppUser.deleted_at.is_(None)))
    if u is None or db.scalar(select(Account.id).where(Account.user_id == u.id)) is not None:
        return None
    return u


def _counts(db: Session, user_id: int) -> tuple[int, int]:
    j = db.scalar(select(func.count()).where(Journal.user_id == user_id, Journal.deleted_at.is_(None))) or 0
    p = db.scalar(select(func.count()).where(Post.user_id == user_id, Post.deleted_at.is_(None))) or 0
    return int(j), int(p)


def _require_agreements(a: Agreements) -> None:
    if not a.all_agreed():
        raise HTTPException(
            status_code=400, detail="만 14세 이상 확인과 이용약관·개인정보 수집 동의가 필요해요"
        )


def _create_account(
    db: Session,
    *,
    device_id: str | None,
    nickname: str,
    email: str | None,
    password_hash: str | None = None,
    google_sub: str | None = None,
) -> tuple[Account, MergeInfo]:
    if nickname_taken(db, nickname):
        raise HTTPException(status_code=409, detail="이미 쓰고 있는 닉네임이에요")
    # 이 기기에서 쓰던 사용자에 계정을 붙인다 → 그동안의 기록이 그대로 계정 것이 된다
    user = _device_user(db, device_id)
    if user is None:
        user = AppUser(device_id=str(uuid.uuid4()))
        db.add(user)
        db.flush()
        j = p = 0
    else:
        j, p = _counts(db, user.id)
    now = utcnow()
    account = Account(
        user_id=user.id,
        email=email,
        password_hash=password_hash,
        google_sub=google_sub,
        nickname=nickname,
        nickname_key=nickname.lower(),
        terms_agreed_at=now,
        privacy_agreed_at=now,
        last_login_at=now,
    )
    db.add(account)
    db.flush()
    return account, MergeInfo(done=j + p > 0, available=False, journals=j, posts=p)


def _finish(db: Session, account: Account, merge: MergeInfo) -> AuthOut:
    token, expires = issue_session(db, account)
    db.commit()
    db.refresh(account)
    return AuthOut(token=token, expires_at=expires, account=account_out(account), merge=merge)


def _login(db: Session, account: Account, device_id: str | None) -> AuthOut:
    account.last_login_at = utcnow()
    merge = MergeInfo(done=False, available=False, journals=0, posts=0)
    device = _device_user(db, device_id)
    if device is not None and device.id != account.user_id:
        j, p = _counts(db, device.id)
        if j + p > 0:
            uj, up = _counts(db, account.user_id)
            if uj + up == 0:
                merge_users(db, device, account.user)  # 계정이 비어 있으면 묻지 않고 옮긴다
                merge = MergeInfo(done=True, available=False, journals=j, posts=p)
            else:
                merge = MergeInfo(done=False, available=True, journals=j, posts=p)
    return _finish(db, account, merge)


# --- 이메일 ---


def signup_email(db: Session, email: str, password: str, nickname: str, agreements: Agreements, device_id):
    _require_agreements(agreements)
    if db.scalar(select(Account.id).where(Account.email == email)) is not None:
        raise HTTPException(status_code=409, detail="이미 가입된 이메일이에요. 로그인해 주세요")
    account, merge = _create_account(
        db, device_id=device_id, nickname=nickname, email=email, password_hash=hash_password(password)
    )
    return _finish(db, account, merge)


def login_email(db: Session, email: str, password: str, device_id) -> AuthOut:
    _check_rate(email)
    account = db.scalar(select(Account).where(Account.email == email, Account.deleted_at.is_(None)))
    if account is None or not verify_password(password, account.password_hash):
        _FAILS[email].append(time.monotonic())
        if account is not None and account.password_hash is None:
            raise HTTPException(
                status_code=401, detail="구글로 가입한 계정이에요. 「구글로 계속하기」를 눌러 주세요"
            )
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 맞지 않아요")
    _FAILS.pop(email, None)
    return _login(db, account, device_id)


# --- 구글 ---


def _google_email(claims: dict) -> str | None:
    email = (claims.get("email") or "").strip().lower()
    return email if email and claims.get("email_verified") in (True, "true") else None


def login_google(db: Session, id_token: str, device_id) -> AuthOut | GoogleSignupNeeded:
    claims = verify_google_token(id_token)
    account = db.scalar(
        select(Account).where(Account.google_sub == claims["sub"], Account.deleted_at.is_(None))
    )
    if account is None:
        email = _google_email(claims)
        # 같은 이메일로 이메일 가입한 계정이 있으면 구글을 그 계정에 연결 (구글이 확인한 이메일만)
        if email:
            account = db.scalar(select(Account).where(Account.email == email, Account.deleted_at.is_(None)))
            if account is not None:
                account.google_sub = claims["sub"]
    if account is None:
        return GoogleSignupNeeded(email=_google_email(claims), name=claims.get("name"))
    return _login(db, account, device_id)


def signup_google(db: Session, id_token: str, nickname: str, agreements: Agreements, device_id) -> AuthOut:
    claims = verify_google_token(id_token)
    existing = db.scalar(
        select(Account).where(Account.google_sub == claims["sub"], Account.deleted_at.is_(None))
    )
    if existing is not None:
        return _login(db, existing, device_id)
    _require_agreements(agreements)
    email = _google_email(claims)
    if email and db.scalar(select(Account.id).where(Account.email == email)) is not None:
        email = None  # 이메일은 이미 다른 계정 것 — 구글 계정 ID 로만 로그인
    account, merge = _create_account(
        db, device_id=device_id, nickname=nickname, email=email, google_sub=claims["sub"]
    )
    return _finish(db, account, merge)


# --- 기기 기록 이전 ---


def merge_users(db: Session, src: AppUser, dst: AppUser) -> None:
    """src(기기 사용자)의 기록·사진·글·댓글·좋아요·즐겨찾기를 dst(계정 사용자)로 옮긴다"""
    from app.services.points import recompute_points

    for model in (Journal, Photo, Post, Comment):
        db.execute(update(model).where(model.user_id == src.id).values(user_id=dst.id))
    # 같은 글에 둘 다 좋아요/신고/즐겨찾기 했으면 하나만 남긴다
    liked = select(PostLike.post_id).where(PostLike.user_id == dst.id)
    db.execute(delete(PostLike).where(PostLike.user_id == src.id, PostLike.post_id.in_(liked)))
    db.execute(update(PostLike).where(PostLike.user_id == src.id).values(user_id=dst.id))
    reported = select(ContentReport.target_type, ContentReport.target_id).where(
        ContentReport.user_id == dst.id
    )
    for t, i in db.execute(reported).all():
        db.execute(
            delete(ContentReport).where(
                ContentReport.user_id == src.id, ContentReport.target_type == t, ContentReport.target_id == i
            )
        )
    db.execute(update(ContentReport).where(ContentReport.user_id == src.id).values(user_id=dst.id))
    faved = select(Favorite.place_id).where(Favorite.user_id == dst.id)
    db.execute(delete(Favorite).where(Favorite.user_id == src.id, Favorite.place_id.in_(faved)))
    db.execute(update(Favorite).where(Favorite.user_id == src.id).values(user_id=dst.id))
    # 포인트는 인증 완료 기록으로 다시 계산 (원장 재계산이라 중복 지급 없음)
    db.execute(delete(PointLedger).where(PointLedger.user_id == src.id))
    src.deleted_at = utcnow()
    db.flush()
    recompute_points(db, dst)


def merge_device(db: Session, account: Account, device_id: str | None) -> MergeInfo:
    device = _device_user(db, device_id)
    if device is None or device.id == account.user_id:
        return MergeInfo(done=False, available=False, journals=0, posts=0)
    j, p = _counts(db, device.id)
    merge_users(db, device, account.user)
    db.commit()
    return MergeInfo(done=True, available=False, journals=j, posts=p)


# --- 닉네임 변경 · 탈퇴 ---


def change_nickname(db: Session, account: Account, nickname: str) -> AccountOut:
    if nickname_taken(db, nickname, exclude_id=account.id):
        raise HTTPException(status_code=409, detail="이미 쓰고 있는 닉네임이에요")
    account.nickname, account.nickname_key = nickname, nickname.lower()
    db.commit()
    return account_out(account)


def delete_account(db: Session, account: Account) -> None:
    """회원 탈퇴: 기록·사진·글·댓글·좋아요·포인트 삭제, 로그인 수단 해제, 세션 만료"""
    now = utcnow()
    uid = account.user_id
    for j in db.scalars(select(Journal).where(Journal.user_id == uid, Journal.deleted_at.is_(None))):
        j.deleted_at = now
        photos.delete_for(db, journal=j)
    for p in db.scalars(select(Post).where(Post.user_id == uid, Post.deleted_at.is_(None))):
        p.deleted_at = now
        photos.delete_for(db, post=p)
    for ph in db.scalars(select(Photo).where(Photo.user_id == uid, Photo.deleted_at.is_(None))):
        ph.deleted_at = now  # 아직 어디에도 안 붙은 사진
        (photos.media_root() / ph.path).unlink(missing_ok=True)
    db.execute(
        update(Comment).where(Comment.user_id == uid, Comment.deleted_at.is_(None)).values(deleted_at=now)
    )
    db.execute(delete(PostLike).where(PostLike.user_id == uid))
    db.execute(delete(Favorite).where(Favorite.user_id == uid))
    # 함께 가는 출조: 내가 참여한 다른 사람의 계획에서는 빠지고, 내가 맡은 준비물 담당도 내려놓는다
    db.execute(delete(TripMember).where(TripMember.user_id == uid))
    db.execute(
        update(TripChecklistItem)
        .where(TripChecklistItem.assignee_user_id == uid)
        .values(assignee_user_id=None)
    )
    # 내가 만든 출조계획은 실제로 지운다 (참여자·초대 코드도 함께.
    # 장소·준비물은 FK CASCADE, 기록 연결은 SET NULL)
    my_plans = select(TripPlan.id).where(TripPlan.user_id == uid)
    db.execute(delete(TripMember).where(TripMember.plan_id.in_(my_plans)))
    db.execute(delete(TripInvite).where(TripInvite.plan_id.in_(my_plans)))
    stop_ids = (
        select(TripStop.id).join(TripPlan, TripPlan.id == TripStop.plan_id).where(TripPlan.user_id == uid)
    )
    db.execute(update(Journal).where(Journal.trip_stop_id.in_(stop_ids)).values(trip_stop_id=None))
    db.execute(
        delete(TripChecklistItem).where(
            TripChecklistItem.plan_id.in_(select(TripPlan.id).where(TripPlan.user_id == uid))
        )
    )
    db.execute(delete(TripStop).where(TripStop.id.in_(stop_ids)))
    db.execute(delete(TripPlan).where(TripPlan.user_id == uid))
    db.execute(delete(PointLedger).where(PointLedger.user_id == uid))
    db.execute(update(AuthSession).where(AuthSession.account_id == account.id).values(revoked_at=now))
    placeholder = f"탈퇴회원{account.id}"
    account.email = account.google_sub = account.password_hash = None
    account.nickname, account.nickname_key = placeholder, placeholder.lower()
    account.deleted_at = now
    account.user.deleted_at = now
    db.commit()
