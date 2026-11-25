"""FCM(Firebase Cloud Messaging) HTTP v1 으로 알림 보내기 (2026-11-25).

- 서비스 계정 키로 JWT 를 서명해 구글 OAuth 토큰(1시간)을 받는다. 새 라이브러리 없이 PyJWT·httpx 만 쓴다
- 키가 없으면 아무것도 보내지 않는다 (로컬·테스트)
- 앱이 지워졌거나 토큰이 바뀐 폰(UNREGISTERED·NOT_FOUND)은 「버릴 토큰」으로 돌려준다
"""

import json
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
import jwt

from app.core.config import get_settings

log = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TOKEN_URL = "https://oauth2.googleapis.com/token"
# 잘못된 요청 내용(INVALID_ARGUMENT)으로 멀쩡한 토큰을 지우지 않게, 폰이 없어진 경우만
DEAD_CODES = {"UNREGISTERED", "NOT_FOUND"}


@dataclass
class Message:
    title: str
    body: str
    data: dict[str, str]  # 앱이 눌렀을 때 열 화면 (예: {"url": "/place/12"})


@lru_cache(maxsize=1)
def _account() -> dict | None:
    raw = get_settings().firebase_service_account.strip()
    if not raw:
        return None
    try:
        return json.loads(raw if raw.startswith("{") else Path(raw).read_text())
    except (OSError, ValueError):
        log.error("Firebase 서비스 계정 키를 읽지 못함 (FIREBASE_SERVICE_ACCOUNT)")
        return None


def enabled() -> bool:
    return _account() is not None


_token: tuple[str, float] | None = None


def _access_token(http: httpx.Client) -> str:
    global _token
    if _token and _token[1] - 60 > time.time():
        return _token[0]
    acc = _account()
    assert acc is not None
    now = int(time.time())
    assertion = jwt.encode(
        {"iss": acc["client_email"], "scope": SCOPE, "aud": TOKEN_URL, "iat": now, "exp": now + 3600},
        acc["private_key"],
        algorithm="RS256",
    )
    res = http.post(
        TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
    )
    res.raise_for_status()
    body = res.json()
    _token = (body["access_token"], time.time() + int(body.get("expires_in", 3600)))
    return _token[0]


def send(tokens: list[str], msg: Message, http: httpx.Client | None = None) -> tuple[int, list[str]]:
    """여러 폰에 같은 알림. (보낸 수, 버릴 토큰) 을 돌려준다"""
    acc = _account()
    if acc is None or not tokens:
        return 0, []
    own = http is None
    http = http or httpx.Client(timeout=get_settings().external_timeout_seconds)
    sent, dead = 0, []
    try:
        url = f"https://fcm.googleapis.com/v1/projects/{acc['project_id']}/messages:send"
        headers = {"Authorization": f"Bearer {_access_token(http)}"}
        for t in tokens:
            payload = {
                "message": {
                    "token": t,
                    "notification": {"title": msg.title, "body": msg.body},
                    "data": msg.data,
                    "android": {"priority": "high", "notification": {"channel_id": "default"}},
                }
            }
            try:
                res = http.post(url, json=payload, headers=headers)
            except httpx.HTTPError as e:
                log.warning("FCM 전송 실패: %s", type(e).__name__)
                continue
            if res.status_code == 200:
                sent += 1
                continue
            try:
                err = res.json().get("error", {})
                codes = {d.get("errorCode") for d in err.get("details", [])} | {err.get("status")}
            except ValueError:
                codes = set()
            if codes & DEAD_CODES:
                dead.append(t)
            else:
                log.warning("FCM 오류 %s %s", res.status_code, sorted(c for c in codes if c))
    finally:
        if own:
            http.close()
    return sent, dead
