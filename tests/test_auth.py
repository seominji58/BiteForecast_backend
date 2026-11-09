"""회원가입·로그인(이메일·구글)·세션·기기 기록 이전·탈퇴·로그인 필요 범위"""

import uuid

import pytest

from app.services import auth as auth_svc
from tests.conftest import AGREE, signup, upload

A = "/api/v1/auth"
J = "/api/v1/journals"
P = "/api/v1/community/posts"


def email() -> str:
    return f"e{uuid.uuid4().hex[:10]}@test.kr"


def nick() -> str:
    return f"n{uuid.uuid4().hex[:8]}"


def bearer(res) -> dict:
    return {"Authorization": f"Bearer {res.json()['token']}"}


def legacy_device_user(client, device_id: str, places) -> None:
    """로그인 기능이 생기기 전처럼 기기 ID 만으로 기록·글을 만든 사용자 (DB 에 직접 생성)"""
    from datetime import UTC, datetime

    from app.core.db import SessionLocal
    from app.models import AppUser, Journal, Post
    from app.models.community import PostCategory

    with SessionLocal() as db:
        u = AppUser(device_id=device_id)
        db.add(u)
        db.flush()
        db.add(Journal(user_id=u.id, place_id=places[0], fished_at=datetime(2026, 11, 1, tzinfo=UTC)))
        db.add(Post(user_id=u.id, category=PostCategory.TIP, title="기기 글", body="본문"))
        db.commit()


# --- 이메일 가입·로그인 ---


def test_signup_login_logout(client):
    e, n = email(), nick()
    res = client.post(
        f"{A}/signup", json={"email": e.upper(), "password": "fish1234", "nickname": n, "agreements": AGREE}
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["account"]["email"] == e and body["account"]["nickname"] == n
    assert body["account"]["provider"] == "email"
    h = bearer(res)
    assert client.get("/api/v1/me/account", headers=h).json()["nickname"] == n

    # 로그인 (대소문자 무시)
    res = client.post(f"{A}/login", json={"email": e.upper(), "password": "fish1234"})
    assert res.status_code == 200
    h2 = bearer(res)
    # 로그아웃하면 그 토큰만 막힌다
    assert client.post(f"{A}/logout", headers=h2).status_code == 204
    assert client.get("/api/v1/me/account", headers=h2).status_code == 401
    assert client.get("/api/v1/me/account", headers=h).status_code == 200


def test_signup_validation(client):
    def go(**kw):
        body = {"email": email(), "password": "fish1234", "nickname": nick(), "agreements": AGREE, **kw}
        return client.post(f"{A}/signup", json=body)

    assert go(email="no-at-sign").status_code == 422
    assert go(password="short1").status_code == 422
    assert go(password="onlyletters").status_code == 422
    assert go(nickname="a").status_code == 422
    assert go(nickname="관리자").status_code == 422
    assert go(nickname="공백 있음").status_code == 422
    assert go(agreements={**AGREE, "over_14": False}).status_code == 400

    taken = nick()
    assert go(nickname=taken).status_code == 201
    assert go(nickname=taken.upper()).status_code == 409  # 대소문자만 달라도 중복
    e = email()
    assert go(email=e).status_code == 201
    assert go(email=e).status_code == 409

    chk = client.get(f"{A}/nickname-check", params={"nickname": taken}).json()
    assert chk["available"] is False
    assert client.get(f"{A}/nickname-check", params={"nickname": nick()}).json()["available"] is True


def test_wrong_password_and_rate_limit(client):
    e = email()
    client.post(
        f"{A}/signup", json={"email": e, "password": "fish1234", "nickname": nick(), "agreements": AGREE}
    )
    for _ in range(5):
        assert client.post(f"{A}/login", json={"email": e, "password": "wrong999"}).status_code == 401
    # 10분 안에 5번 틀리면 맞는 비밀번호도 잠시 막힘
    assert client.post(f"{A}/login", json={"email": e, "password": "fish1234"}).status_code == 429


def test_password_is_hashed():
    h = auth_svc.hash_password("fish1234")
    assert "fish1234" not in h and h.startswith("scrypt$")
    assert auth_svc.verify_password("fish1234", h) and not auth_svc.verify_password("fish12345", h)


# --- 로그인 필요 범위 ---


def test_reading_is_open_writing_needs_login(client, places):
    assert client.get(P).status_code == 200  # 커뮤니티 읽기
    assert client.get(f"/api/v1/places/{places[0]}").status_code == 200
    assert client.post(P, json={"category": "tip", "title": "제목", "body": "본문"}).status_code == 401
    assert client.get(J).status_code == 401
    assert client.get("/api/v1/me/points").status_code == 401
    res = client.post(J, json={"place_id": places[0], "fished_at": "2026-11-01T06:00:00+09:00"})
    assert res.status_code == 401 and res.json()["error"]["message"] == "로그인이 필요해요"
    # 기기 ID 만으로는 더 이상 쓸 수 없다
    assert client.get(J, headers={"X-Device-Id": str(uuid.uuid4())}).status_code == 401


# --- 기기 기록 이전 ---


def test_first_signup_keeps_device_records(client, places):
    dev = str(uuid.uuid4())
    legacy_device_user(client, dev, places)
    res = client.post(
        f"{A}/signup",
        json={"email": email(), "password": "fish1234", "nickname": nick(), "agreements": AGREE},
        headers={"X-Device-Id": dev},
    )
    assert res.json()["merge"] == {"done": True, "available": False, "journals": 1, "posts": 1}
    assert len(client.get(J, headers=bearer(res)).json()) == 1


def test_login_on_new_device_merges(client, places):
    e = email()
    h = signup(client, email=e)
    # 계정이 비어 있으면 다른 기기 기록을 자동으로 옮긴다
    dev = str(uuid.uuid4())
    legacy_device_user(client, dev, places)
    res = client.post(f"{A}/login", json={"email": e, "password": "fish1234"}, headers={"X-Device-Id": dev})
    assert res.json()["merge"]["done"] is True
    assert len(client.get(J, headers=h).json()) == 1

    # 계정에 기록이 있으면 묻는다 → 동의하면 옮긴다
    dev2 = str(uuid.uuid4())
    legacy_device_user(client, dev2, places)
    res = client.post(f"{A}/login", json={"email": e, "password": "fish1234"}, headers={"X-Device-Id": dev2})
    m = res.json()["merge"]
    assert m["done"] is False and m["available"] is True and m["journals"] == 1
    assert len(client.get(J, headers=h).json()) == 1
    out = client.post(f"{A}/merge-device", headers={**bearer(res), "X-Device-Id": dev2}).json()
    assert out["done"] is True
    assert len(client.get(J, headers=h).json()) == 2
    # 같은 기기에서 다시 로그인하면 옮길 것이 없다
    res = client.post(f"{A}/login", json={"email": e, "password": "fish1234"}, headers={"X-Device-Id": dev2})
    assert res.json()["merge"]["available"] is False


# --- 구글 ---


@pytest.fixture()
def fake_google(monkeypatch):
    """구글 서명 검증 대신 토큰 문자열로 사용자 정보를 돌려준다"""
    users: dict[str, dict] = {}

    def verify(token: str) -> dict:
        if token not in users:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="bad token")
        return users[token]

    monkeypatch.setattr(auth_svc, "verify_google_token", verify)
    return users


def test_google_signup_and_login(client, fake_google):
    tok = "google-token-" + uuid.uuid4().hex
    e = email()
    fake_google[tok] = {"sub": uuid.uuid4().hex, "email": e, "email_verified": True, "name": "김낚시"}
    first = client.post(f"{A}/google", json={"id_token": tok}).json()
    assert first == {"status": "signup_required", "email": e, "name": "김낚시"}

    n = nick()
    res = client.post(f"{A}/google/signup", json={"id_token": tok, "nickname": n, "agreements": AGREE})
    assert res.status_code == 201, res.text
    assert res.json()["account"]["provider"] == "google" and res.json()["account"]["email"] == e
    again = client.post(f"{A}/google", json={"id_token": tok}).json()
    assert again["status"] == "ok" and again["account"]["nickname"] == n
    # 구글 계정은 비밀번호 로그인 불가 (안내 문구)
    res = client.post(f"{A}/login", json={"email": e, "password": "fish1234"})
    assert res.status_code == 401 and "구글" in res.json()["error"]["message"]


def test_google_links_to_existing_email_account(client, fake_google):
    e = email()
    h = signup(client, email=e)
    tok = "google-token-" + uuid.uuid4().hex
    fake_google[tok] = {"sub": uuid.uuid4().hex, "email": e, "email_verified": True}
    res = client.post(f"{A}/google", json={"id_token": tok}).json()
    assert res["status"] == "ok"
    assert res["account"]["id"] == client.get("/api/v1/me/account", headers=h).json()["id"]


def test_google_not_configured(client):
    res = client.post(f"{A}/google", json={"id_token": "x" * 40})
    assert res.status_code == 503
    assert client.get(f"{A}/config").json() == {"google": False, "email": True}


# --- 탈퇴 ---


def test_delete_account(client, places):
    e = email()
    h = signup(client, email=e)
    ph = upload(client, h, purpose="post")
    post = client.post(
        P, json={"category": "tip", "title": "탈퇴 전 글", "body": "본문", "photo_ids": [ph["id"]]}, headers=h
    )
    client.post(J, json={"place_id": places[0], "fished_at": "2026-11-01T06:00:00+09:00"}, headers=h)

    assert client.delete("/api/v1/me/account", headers=h).status_code == 204
    assert client.get("/api/v1/me/account", headers=h).status_code == 401  # 세션 만료
    assert client.get(f"{P}/{post.json()['id']}").status_code == 404  # 글 삭제
    assert client.get(f"/api/v1/photos/{ph['id']}").status_code == 404  # 사진 삭제
    # 같은 이메일로 다시 가입할 수 있다 (새 계정, 기록 없음)
    h2 = signup(client, email=e)
    assert client.get(J, headers=h2).json() == []
