"""소셜 로그인 공통 구조: 카카오 OIDC 검증(nonce·aud·서명) · 로그인 수단 표 · 예전 구글 계정 옮기기 · 탈퇴"""

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import get_settings
from app.services import social
from tests.conftest import AGREE

A = "/api/v1/auth"
APP_KEY = "test-kakao-native-key"


class _Key:
    def __init__(self, key):
        self.key = key


class _FakeJwks:
    """카카오 공개키 조회만 바꿔 끼운다 (서명 검증은 진짜로 한다)"""

    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return _Key(self.public_key)


@pytest.fixture()
def kakao(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(get_settings(), "kakao_native_app_key", APP_KEY)
    monkeypatch.setattr(social, "_kakao_jwks", _FakeJwks(private.public_key()))

    def token(sub: str, nonce: str | None, *, aud: str = APP_KEY, key=private, exp_in: int = 3600) -> str:
        now = int(time.time())
        claims = {"iss": "https://kauth.kakao.com", "aud": aud, "sub": sub, "iat": now, "exp": now + exp_in}
        if nonce is not None:
            claims["nonce"] = nonce
        claims["nickname"] = "카카오낚시"
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})

    return token


def nonce(client) -> str:
    res = client.post(f"{A}/nonce")
    assert res.status_code == 200
    return res.json()["nonce"]


def nick() -> str:
    return "k" + uuid.uuid4().hex[:8]


def test_kakao_signup_and_login(client, kakao):
    sub = str(uuid.uuid4().int)[:10]
    n = nonce(client)
    first = client.post(f"{A}/social/kakao", json={"token": kakao(sub, n), "nonce": n}).json()
    assert first == {"status": "signup_required", "provider": "kakao", "email": None, "name": "카카오낚시"}

    n = nonce(client)
    name = nick()
    res = client.post(
        f"{A}/social/kakao/signup",
        json={"token": kakao(sub, n), "nonce": n, "nickname": name, "agreements": AGREE},
    )
    assert res.status_code == 201, res.text
    acc = res.json()["account"]
    assert acc["provider"] == "kakao" and acc["providers"] == ["kakao"] and acc["email"] is None

    n = nonce(client)
    again = client.post(f"{A}/social/kakao", json={"token": kakao(sub, n), "nonce": n}).json()
    assert again["status"] == "ok" and again["account"]["nickname"] == name
    assert client.get(f"{A}/config").json()["kakao"] is True


def test_kakao_rejects_bad_tokens(client, kakao):
    sub = "99" + str(uuid.uuid4().int)[:8]
    n = nonce(client)
    post = lambda body: client.post(f"{A}/social/kakao", json=body)  # noqa: E731
    # 다른 앱(aud)용 토큰
    assert post({"token": kakao(sub, n, aud="other-app"), "nonce": n}).status_code == 401
    # 토큰 안 nonce 와 보낸 nonce 가 다름
    other = nonce(client)
    assert post({"token": kakao(sub, other), "nonce": n}).status_code == 401
    # 서버가 내지 않은(위조) nonce
    fake = "123.abc.def"
    assert post({"token": kakao(sub, fake), "nonce": fake}).status_code == 401
    # nonce 없음
    assert post({"token": kakao(sub, None)}).status_code == 401
    # 다른 키로 서명
    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert post({"token": kakao(sub, n, key=stranger), "nonce": n}).status_code == 401
    # 만료
    assert post({"token": kakao(sub, n, exp_in=-10), "nonce": n}).status_code == 401


def test_expired_nonce(client, kakao, monkeypatch):
    n = nonce(client)
    real = time.time
    monkeypatch.setattr(social.time, "time", lambda: real() + social.NONCE_TTL + 5)
    res = client.post(f"{A}/social/kakao", json={"token": kakao("777", n), "nonce": n})
    assert res.status_code == 401 and "만료" in res.json()["error"]["message"]


def test_kakao_not_configured(client):
    res = client.post(f"{A}/social/kakao", json={"token": "x" * 40, "nonce": "1.2.3"})
    assert res.status_code == 503
    assert client.post(f"{A}/social/naver", json={"token": "x" * 40}).status_code == 422


def test_legacy_google_account_moves_to_identity(client, monkeypatch):
    """0005 전에 만든 구글 계정(google_sub 만 있음)도 새 API 로 로그인되고, 로그인 수단 표에 옮겨진다"""
    from app.core.db import SessionLocal
    from app.models import Account, AccountIdentity, AppUser
    from app.models.base import utcnow
    from app.services import auth as auth_svc

    sub = "legacy-" + uuid.uuid4().hex
    with SessionLocal() as db:
        u = AppUser(device_id=str(uuid.uuid4()))
        db.add(u)
        db.flush()
        name = nick()
        db.add(
            Account(
                user_id=u.id,
                google_sub=sub,
                nickname=name,
                nickname_key=name,
                terms_agreed_at=utcnow(),
                privacy_agreed_at=utcnow(),
            )
        )
        db.commit()
    monkeypatch.setattr(auth_svc, "verify_google_token", lambda t: {"sub": sub, "name": "예전"})
    res = client.post(f"{A}/social/google", json={"token": "g" * 30}).json()
    assert res["status"] == "ok" and res["account"]["nickname"] == name
    assert res["account"]["providers"] == ["google"]
    with SessionLocal() as db:
        rows = db.query(AccountIdentity).filter(AccountIdentity.subject == sub).all()
        assert len(rows) == 1 and rows[0].provider == "google"


def test_delete_account_removes_identity(client, kakao):
    sub = "88" + str(uuid.uuid4().int)[:8]
    n = nonce(client)
    res = client.post(
        f"{A}/social/kakao/signup",
        json={"token": kakao(sub, n), "nonce": n, "nickname": nick(), "agreements": AGREE},
    ).json()
    h = {"Authorization": f"Bearer {res['token']}"}
    assert client.delete("/api/v1/me/account", headers=h).status_code == 204
    n = nonce(client)
    again = client.post(f"{A}/social/kakao", json={"token": kakao(sub, n), "nonce": n}).json()
    assert again["status"] == "signup_required"  # 탈퇴 뒤 같은 카카오 계정은 새로 가입
