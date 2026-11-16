"""커뮤니티 v2: 자유게시판 · 내 글 고치기 · 낚시터별 조황 요약 (2026-11-16)"""

import uuid

import pytest

from app.core.db import SessionLocal
from app.models import Place, Region
from tests.conftest import signup
from tests.test_community import URL, post


@pytest.fixture()
def fresh_place(client) -> int:
    """다른 테스트 글이 없는 새 낚시터 (조황 집계 수를 정확히 보려고)"""
    with SessionLocal() as db:
        r = Region(name=f"조황테스트 {uuid.uuid4().hex[:6]}")
        r.places = [Place(name="조황 테스트 방파제")]
        db.add(r)
        db.commit()
        return r.places[0].id


def test_free_board(client):
    h = signup(client)
    p = post(client, h, category="free", title="오늘 점심 뭐 드셨어요", body="낚시 말고 아무 얘기")
    assert p["category"] == "free"
    listed = client.get(f"{URL}/posts", params={"category": "free"}, headers=h).json()
    assert any(x["id"] == p["id"] for x in listed) and all(x["category"] == "free" for x in listed)


def test_edit_my_post(client, places):
    h = signup(client)
    p = post(client, h, place_id=places[0], location_visibility="place", species_code="black_porgy")
    r = client.patch(f"{URL}/posts/{p['id']}", json={"title": "고친 제목", "location_visibility": "region"}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["title"] == "고친 제목" and d["location_visibility"] == "region"
    assert d["body"] == p["body"]  # 안 보낸 칸은 그대로
    # 낚시터 없이 「낚시터 이름 공개」는 안 됨
    r = client.patch(f"{URL}/posts/{p['id']}", json={"place_id": None, "location_visibility": "place"}, headers=h)
    assert r.status_code == 400


def test_cannot_edit_others_post(client):
    p = post(client, signup(client))
    r = client.patch(f"{URL}/posts/{p['id']}", json={"title": "남의 글"}, headers=signup(client))
    assert r.status_code == 403


def test_catch_summary_counts_only_public_place_catches(client, fresh_place):
    h = signup(client)
    pid = fresh_place
    post(client, h, place_id=pid, location_visibility="place", species_code="black_porgy")
    post(client, h, place_id=pid, location_visibility="place", species_etc="광어")
    post(client, h, place_id=pid, location_visibility="region", species_code="black_porgy")  # 지역만 → 안 셈
    post(client, h, category="question", place_id=pid, location_visibility="place")  # 질문 → 안 셈
    rows = client.get(f"{URL}/catch-summary", params={"days": 14}, headers=signup(client)).json()
    row = next(x for x in rows if x["place_id"] == pid)
    assert row["posts"] == 2
    assert set(row["species"]) == {"감성돔", "광어"}


def test_catch_summary_hides_blocked_authors(client, fresh_place):
    author, viewer = signup(client), signup(client)
    p = post(client, author, place_id=fresh_place, location_visibility="place")
    before = client.get(f"{URL}/catch-summary", headers=viewer).json()
    assert any(x["place_id"] == fresh_place for x in before)
    r = client.post(f"{URL}/blocks", json={"target_type": "post", "target_id": p["id"]}, headers=viewer)
    assert r.status_code in (200, 201), r.text
    after = client.get(f"{URL}/catch-summary", headers=viewer).json()
    assert all(x["place_id"] != fresh_place for x in after)
