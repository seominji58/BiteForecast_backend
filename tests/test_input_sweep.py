"""사용성 점검 (2026-11-26 친구 테스트): 이모티콘·특수문자·긴 글을 글자 입력 칸마다 넣어 본다.

- 정상 입력(이모티콘 포함)은 저장되고 그대로 돌아와야 한다 (4바이트 이모지·합자 이모지·한자·특수문자)
- 막히는 입력은 422 + 한국어 문장 (영어 원문 「String should …」가 앱에 보이면 안 된다)
"""

import re
from datetime import timedelta

import pytest

from app.core.timeutil import today_kst
from tests.conftest import signup

EMOJI = ["🎣", "🐟대물!!", "👨‍👩‍👧 가족 출조", "감성돔 🐠🐠 ㅋㅋ", "<b>&\"'</b> %s \\n", "🇰🇷 낚시"]
HANGUL = re.compile(r"[가-힣]")


def _ko_error(r):
    assert r.status_code == 422, r.text
    msg = r.json()["error"]["message"]
    assert HANGUL.search(msg) and "String should" not in msg and "Input should" not in msg, msg
    return msg


@pytest.mark.parametrize("text", EMOJI)
def test_post_and_comment_accept_emoji(client, text):
    h = signup(client)
    r = client.post(
        "/api/v1/community/posts", json={"category": "free", "title": text, "body": text}, headers=h
    )
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["title"] == text.strip() and p["body"] == text.strip()
    c = client.post(f"/api/v1/community/posts/{p['id']}/comments", json={"body": text}, headers=h)
    assert c.status_code in (200, 201), c.text
    assert any(x["body"] == text.strip() for x in c.json()["comments"])


@pytest.mark.parametrize("text", EMOJI)
def test_journal_text_fields_accept_emoji(client, places, text):
    h = signup(client)
    r = client.post(
        "/api/v1/journals",
        json={
            "place_id": places[0],
            "fished_at": "2026-11-01T06:00:00+09:00",
            "memo": text,
            "bait": text[:20],
            "rig": text[:20],
            "species_etc": text[:20],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    j = r.json().get("journal", r.json())
    assert j["memo"] in (text, text.strip())


@pytest.mark.parametrize("text", EMOJI)
def test_trip_and_spot_accept_emoji(client, places, text):
    h = signup(client)
    d = str(today_kst() + timedelta(days=3))
    r = client.post(
        "/api/v1/me/trips",
        json={
            "title": text,
            "memo": text,
            "start_date": d,
            "end_date": d,
            "stops": [{"day": d, "place_id": places[0]}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    s = client.post(
        "/api/v1/me/spots", json={"name": text[:40], "memo": text, "lat": 35.1, "lon": 129.0}, headers=h
    )
    assert s.status_code in (200, 201), s.text


def test_rejections_are_korean(client, places):
    h = signup(client)
    long = "가" * 3000
    _ko_error(
        client.post("/api/v1/community/posts", json={"category": "free", "title": "", "body": "x"}, headers=h)
    )
    _ko_error(
        client.post(
            "/api/v1/community/posts", json={"category": "free", "title": long, "body": "x"}, headers=h
        )
    )
    _ko_error(
        client.post(
            "/api/v1/community/posts", json={"category": "free", "title": "a", "body": long}, headers=h
        )
    )
    _ko_error(
        client.post(
            "/api/v1/community/posts", json={"category": "nope", "title": "a", "body": "x"}, headers=h
        )
    )
    _ko_error(client.post("/api/v1/community/posts", json={"title": "a"}, headers=h))
    j = {"place_id": places[0], "fished_at": "2026-11-01T06:00:00+09:00"}
    assert "600" in _ko_error(client.post("/api/v1/journals", json={**j, "max_length_cm": 700}, headers=h))
    _ko_error(client.post("/api/v1/journals", json={**j, "count": "많이"}, headers=h))
    _ko_error(client.post("/api/v1/journals", json={**j, "count": -1}, headers=h))
    _ko_error(client.post("/api/v1/journals", json={**j, "fished_at": "어제"}, headers=h))
    # 닉네임은 이모티콘을 쓸 수 없다 — 이유를 한국어로
    msg = _ko_error(
        client.post(
            "/api/v1/auth/signup",
            json={
                "email": "emoji@test.kr",
                "password": "fish1234",
                "nickname": "낚시왕🎣",
                "agreements": {"over_14": True, "terms": True, "privacy": True},
            },
        )
    )
    assert "닉네임" in msg
