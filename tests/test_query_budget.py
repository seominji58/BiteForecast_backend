"""쿼리 수 상한 (원격 DB 성능 회귀 방지, 2026-11-11 Supabase 전환).

Supabase 는 왕복마다 수~수십 ms 가 들어, 장소·항목마다 조회(N+1)하면 화면이 수십 초 걸린다.
목록이 길어져도 쿼리 수가 함께 늘지 않아야 한다.
"""

from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import event

from app.core.db import SessionLocal, engine
from app.core.timeutil import today_kst
from app.models import Place, Region
from tests.conftest import signup
from tests.test_journals import create as create_journal


@contextmanager
def count_queries():
    n = [0]

    def on(*_a):
        n[0] += 1

    event.listen(engine, "before_cursor_execute", on)
    try:
        yield n
    finally:
        event.remove(engine, "before_cursor_execute", on)


def _get(client, path, headers=None):
    with count_queries() as n:
        r = client.get(path, headers=headers)
    assert r.status_code == 200, r.text
    return n[0]


def _add_places(k: int) -> None:
    with SessionLocal() as db:
        r = Region(name="충남 태안군")
        r.places = [Place(name=f"예산-{i}", lat=36.7 + i * 0.01, lon=126.1) for i in range(k)]
        db.add(r)
        db.commit()


def test_places_and_summary_do_not_scale_with_places(client, places):
    import app.services.summary as summary

    day = str(today_kst())
    summary._cache.clear()
    before_sum = _get(client, f"/api/v1/places-summary?date={day}")
    before_list = _get(client, "/api/v1/places")
    _add_places(15)
    # 장소가 바뀌면 위치 판단 캐시를 한 번 새로 계산한다 (장소 수와 무관한 고정 비용) → 먼저 데운다
    summary._cache.clear()
    _get(client, f"/api/v1/places-summary?date={day}")
    summary._cache.clear()
    after_sum = _get(client, f"/api/v1/places-summary?date={day}")
    after_list = _get(client, "/api/v1/places")
    # 장소가 15곳 늘어도 쿼리 수는 그대로
    assert after_sum <= before_sum and after_sum <= 30, (before_sum, after_sum)
    assert after_list <= before_list and after_list <= 15, (before_list, after_list)


def test_place_detail_budget(client, places):
    assert _get(client, f"/api/v1/places/{places[0]}/conditions?date={today_kst()}") <= 20


def test_trips_and_journals_lists_do_not_scale(client, places):
    h = signup(client)
    d = str(today_kst() + timedelta(days=3))

    def add_trip():
        stops = [{"day": d, "place_id": p} for p in places]
        r = client.post("/api/v1/me/trips", json={"start_date": d, "end_date": d, "stops": stops}, headers=h)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    tid = add_trip()
    create_journal(client, h, place_id=places[0])
    one_trips = _get(client, "/api/v1/me/trips", h)
    one_journals = _get(client, "/api/v1/journals", h)
    one_outlook = _get(client, f"/api/v1/me/trips/{tid}/outlook", h)
    for _ in range(4):
        add_trip()
        create_journal(client, h, place_id=places[1])
    assert _get(client, "/api/v1/me/trips", h) <= one_trips + 2
    assert _get(client, "/api/v1/journals", h) <= one_journals + 2
    # 계획 하나의 해황: 장소 수(3)만큼 늘 수 있지만 장소당 수십 번이면 안 된다
    assert one_outlook <= 60, one_outlook


def test_community_list_does_not_scale(client):
    from tests.test_community import post

    h = signup(client)
    post(client, h)
    one = _get(client, "/api/v1/community/posts", h)
    for _ in range(4):
        post(client, h)
    assert _get(client, "/api/v1/community/posts", h) <= one + 2
