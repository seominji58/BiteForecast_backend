"""기상청 중기해상예보 (4~10일 뒤 해역별 파고 범위) — 해석·발표 시각·요약 연결"""

from datetime import date, datetime, timedelta

from app.clients.kma_mid_sea import latest_tm_fc, parse_item
from app.core.db import SessionLocal
from app.core.timeutil import KST, today_kst
from app.models import MidSeaForecast, Place, Region
from app.models.base import utcnow
from app.services import summary as summary_service

# 2026-11-17 06시 서해중부 실제 응답 일부
ITEM = {
    "wf4Am": "구름많고 비/눈", "wf4Pm": "맑음", "wh4AAm": 1.0, "wh4APm": 1.0, "wh4BAm": 2.5, "wh4BPm": 2.5,
    "wf8": "맑음", "wh8A": 1.0, "wh8B": 2.0,
}


def test_parse_am_pm_and_day():
    tm = datetime(2026, 11, 17, 6, tzinfo=KST)
    rows = parse_item(ITEM, tm)
    am = next(r for r in rows if r.target_date == date(2026, 11, 21) and r.period == "am")
    assert (am.wave_min, am.wave_max, am.weather) == (1.0, 2.5, "구름많고 비/눈")
    day8 = next(r for r in rows if r.target_date == date(2026, 11, 25))
    assert day8.period == "day" and day8.wave_max == 2.0


def test_latest_tm_fc():
    k = lambda h, m=0: datetime(2026, 11, 17, h, m, tzinfo=KST)  # noqa: E731
    assert latest_tm_fc(k(9)) == k(6)
    assert latest_tm_fc(k(6, 5)) == k(18) - timedelta(days=1)  # 발표 뒤 15분 전이면 전날 18시
    assert latest_tm_fc(k(19)) == k(18)


def test_summary_attaches_region_mid_sea(client):
    """충남 낚시터 → 서해중부 해역 중기예보가 붙고, 최신 발표분만 쓴다"""
    day = today_kst() + timedelta(days=5)
    with SessionLocal() as db:
        r = Region(name="충남 중기시험군")
        r.places = [Place(name="중기 시험 방파제", lat=36.5, lon=126.2)]
        db.add(r)
        old = datetime.now(KST) - timedelta(days=1)
        new = datetime.now(KST)
        for tm, hi in ((old, 9.9), (new, 2.5)):
            for per in ("am", "pm"):
                db.add(
                    MidSeaForecast(
                        region="서해중부", tm_fc=tm, target_date=day.isoformat(), period=per,
                        wave_min=1.0, wave_max=hi if per == "am" else 2.0, weather="맑음", fetched_at=utcnow(),
                    )
                )
        db.commit()
        pid = r.places[0].id
    summary_service._cache.clear()
    rows = client.get(f"/api/v1/places-summary?date={day}").json()["places"]
    mid = next(x for x in rows if x["place_id"] == pid)["mid_sea"]
    assert mid["region"] == "서해중부"
    assert (mid["wave_min"], mid["wave_max"]) == (1.0, 2.5)  # 예전 발표(9.9)는 쓰지 않음
    assert [p["period"] for p in mid["periods"]] == ["am", "pm"]
