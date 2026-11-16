"""소셜 로그인 토큰 검증 (소셜 로그인·지도 SDK 설계 2026-11-16 §3-3).

제공자마다 「이 토큰이 그 제공자가 우리 앱용으로 발급한 것인지」만 확인하고,
같은 모양(SocialClaims)으로 돌려준다.
- 구글: ID 토큰 — 구글 공개키 서명 + aud ∈ GOOGLE_CLIENT_IDS + 발급자
- 카카오: OIDC ID 토큰 — 카카오 공개키 서명(RS256) + iss + aud = 네이티브 앱 키 + exp
  + nonce(서버가 발급한 값)
- 네이버: ID 토큰을 주지 않아 토큰이 우리 앱용인지 확인할 방법이 정해지지 않았다 → 아직 지원하지 않음

nonce 는 서버가 서명해 내주는 일회성 값(5분)이다.
서버에 저장하지 않으므로 서버가 여러 대여도 같은 키로 확인된다.
"""

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

import jwt
from fastapi import HTTPException

from app.core.config import get_settings

PROVIDERS = ("google", "kakao")
NONCE_TTL = 300


@dataclass(frozen=True)
class SocialClaims:
    provider: str
    subject: str
    email: str | None  # 제공자가 「확인됨」으로 준 이메일만 (같은 이메일 계정에 자동 연결할 때만 쓴다)
    name: str | None


def enabled() -> dict[str, bool]:
    s = get_settings()
    return {"google": bool(google_client_ids()), "kakao": bool(s.kakao_native_app_key.strip())}


# --- nonce ---


def _nonce_key() -> bytes:
    s = get_settings()
    if s.auth_nonce_secret:
        return s.auth_nonce_secret.encode()
    # 따로 정하지 않으면 DB 주소(비밀값)에서 만든다 → 같은 DB 를 쓰는 서버는 모두 같은 키
    return hashlib.sha256(("biteforecast-nonce:" + s.database_url).encode()).digest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def issue_nonce() -> tuple[str, int]:
    body = f"{int(time.time())}.{_b64(secrets.token_bytes(12))}"
    sig = _b64(hmac.new(_nonce_key(), body.encode(), hashlib.sha256).digest()[:16])
    return f"{body}.{sig}", NONCE_TTL


def check_nonce(nonce: str | None) -> None:
    try:
        ts, rand, sig = (nonce or "").split(".")
        want = _b64(hmac.new(_nonce_key(), f"{ts}.{rand}".encode(), hashlib.sha256).digest()[:16])
        ok = hmac.compare_digest(sig, want) and 0 <= time.time() - int(ts) <= NONCE_TTL
    except ValueError:
        ok = False
    if not ok:
        raise HTTPException(status_code=401, detail="로그인 요청이 만료됐어요. 다시 시도해 주세요")


# --- 구글 ---

_GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISS = ["accounts.google.com", "https://accounts.google.com"]
_google_jwks: jwt.PyJWKClient | None = None


def google_client_ids() -> list[str]:
    return [x.strip() for x in get_settings().google_client_ids.split(",") if x.strip()]


def verify_google(token: str) -> dict:
    """구글이 서명한 ID 토큰인지, 우리 앱(클라이언트 ID)용인지 확인하고 내용을 돌려준다"""
    global _google_jwks
    audiences = google_client_ids()
    if not audiences:
        raise HTTPException(
            status_code=503, detail="구글 로그인이 아직 설정되지 않았어요 (GOOGLE_CLIENT_IDS)"
        )
    try:
        if _google_jwks is None:
            _google_jwks = jwt.PyJWKClient(_GOOGLE_CERTS, cache_keys=True, lifespan=3600)
        key = _google_jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=audiences, issuer=_GOOGLE_ISS)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401, detail="구글 로그인 정보를 확인하지 못했어요. 다시 시도해 주세요"
        ) from None
    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="구글 계정 정보가 없어요")
    return claims


def _google_claims(claims: dict) -> SocialClaims:
    email = (claims.get("email") or "").strip().lower()
    verified = email and claims.get("email_verified") in (True, "true")
    return SocialClaims("google", str(claims["sub"]), email if verified else None, claims.get("name"))


# --- 카카오 (OIDC) ---

_KAKAO_JWKS = "https://kauth.kakao.com/.well-known/jwks.json"
_KAKAO_ISS = "https://kauth.kakao.com"
_kakao_jwks: jwt.PyJWKClient | None = None


def verify_kakao(token: str, nonce: str | None) -> dict:
    """카카오가 서명한 OIDC ID 토큰인지, 우리 앱(네이티브 앱 키)용인지, 서버가 낸 nonce 인지 확인한다"""
    global _kakao_jwks
    app_key = get_settings().kakao_native_app_key.strip()
    if not app_key:
        raise HTTPException(
            status_code=503, detail="카카오 로그인이 아직 설정되지 않았어요 (KAKAO_NATIVE_APP_KEY)"
        )
    check_nonce(nonce)
    try:
        if _kakao_jwks is None:
            # 카카오 공개키는 캐시해서 쓴다 (너무 자주 요청하면 막힐 수 있다 — 카카오 문서)
            _kakao_jwks = jwt.PyJWKClient(_KAKAO_JWKS, cache_keys=True, lifespan=3600)
        key = _kakao_jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=app_key, issuer=_KAKAO_ISS)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401, detail="카카오 로그인 정보를 확인하지 못했어요. 다시 시도해 주세요"
        ) from None
    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="카카오 계정 정보가 없어요")
    if not hmac.compare_digest(str(claims.get("nonce") or ""), nonce or ""):
        raise HTTPException(status_code=401, detail="로그인 요청이 맞지 않아요. 다시 시도해 주세요")
    return claims


def _kakao_claims(claims: dict) -> SocialClaims:
    # 이메일은 비즈 앱 전환 뒤에만 받을 수 있고, 지금은 닉네임만 받는다 → 자동 연결에 쓰지 않는다
    return SocialClaims("kakao", str(claims["sub"]), None, claims.get("nickname"))


def verify(provider: str, token: str, nonce: str | None) -> SocialClaims:
    if provider == "google":
        return _google_claims(verify_google(token))
    if provider == "kakao":
        return _kakao_claims(verify_kakao(token, nonce))
    raise HTTPException(status_code=404, detail="지원하지 않는 로그인 방법이에요")
