"""해상 특보 파싱·장소별 판정 (2026-11-05 07:00 실제 발표 원문 기반)"""

import json
from datetime import timedelta

import pytest

from app.clients.kma_warning import parse_active, parse_preliminary, split_areas
from app.core.db import SessionLocal
from app.models import MarineWarningSnapshot, Place, Region
from app.models.base import utcnow
from app.models.enums import PlaceType
from app.services.warning import evaluate

T6 = (
    "o 강풍주의보 : 전라남도(흑산도.홍도), 제주도\r\n"
    "o 풍랑주의보 : 서해남부북쪽바깥먼바다, 서해남부남쪽바깥먼바다, 남해동부안쪽먼바다, "
    "남해동부바깥먼바다, 남해서부서쪽먼바다, 제주도전해상"
)
T7 = (
    "(1) 풍랑 예비특보\r\n"
    "o 11월 05일 오전(06시~12시) : 서해남부남쪽안쪽먼바다\r\n"
    "o 11월 06일 새벽(00시~06시) : 동해중부안쪽먼바다, 동해중부바깥먼바다, 서해중부안쪽먼바다\r\n"
    "o 11월 06일 오전(06시~12시) : 동해남부남쪽안쪽먼바다, 동해중부앞바다\r\n"
    "(2) 강풍 예비특보\r\n"
    "o 11월 06일 새벽(00시~06시) : 서해5도, 강원도(고성산지, 인제산지), 충청남도(보령도서)\r\n"
)


def test_split_keeps_commas_inside_parentheses():
    assert split_areas("서해5도, 강원도(고성산지, 인제산지), 울릉도.독도") == [
        "서해5도",
        "강원도(고성산지, 인제산지)",
        "울릉도.독도",
    ]


def test_parse():
    active = parse_active(T6)
    assert [a.type for a in active] == ["강풍주의보", "풍랑주의보"]
    assert "남해동부안쪽먼바다" in active[1].areas and "제주도전해상" in active[1].areas
    prelim = parse_preliminary(T7)
    assert prelim[0].type == "풍랑 예비특보" and prelim[0].when == "11월 05일 오전(06시~12시)"
    assert prelim[-1].type == "강풍 예비특보" and "충청남도(보령도서)" in prelim[-1].areas
    assert parse_active("o 없음\r\n") == []


@pytest.fixture(scope="module")
def warn_places(client):
    with SessionLocal() as db:
        db.add(
            MarineWarningSnapshot(
                issued_at=utcnow(),
                fetched_at=utcnow(),
                active_json=json.dumps([{"type": a.type, "areas": a.areas} for a in parse_active(T6)]),
                preliminary_json=json.dumps(
                    [{"type": p.type, "when": p.when, "areas": p.areas} for p in parse_preliminary(T7)]
                ),
                raw_active=T6,
                raw_preliminary=T7,
            )
        )
        made = {}
        for region_name, name, ptype in [
            ("부산 해운대구", "특보-미포", PlaceType.WHARF),
            ("제주 제주시", "특보-김녕", PlaceType.POINT),
            ("전남 신안군", "특보-선상", PlaceType.BOAT),
            ("충남 보령시", "특보-대천", PlaceType.WHARF),
            ("경기 화성시", "특보-국화도", PlaceType.POINT),
            ("해상", "특보-미상", PlaceType.BOAT),
        ]:
            r = Region(name=f"{region_name}")
            p = Place(name=name, type=ptype, lat=35.0, lon=128.0)
            r.places = [p]
            db.add(r)
            db.flush()
            made[name] = p.id
        db.commit()
        return made


def _eval(place_id):
    with SessionLocal() as db:
        return evaluate(db, db.get(Place, place_id))


def test_levels(warn_places):
    # 부산: 남해동부 「먼바다」 풍랑주의보만 → 연안 장소는 인근 해역
    busan = _eval(warn_places["특보-미포"])
    assert busan.level == "nearby" and busan.active[0].areas == ["남해동부안쪽먼바다", "남해동부바깥먼바다"]

    # 제주: 「제주도전해상」 풍랑주의보 → 발효
    assert _eval(warn_places["특보-김녕"]).level == "warning"

    # 서해남부 먼바다 + 선상 포인트 → 발효
    assert _eval(warn_places["특보-선상"]).level == "warning"

    # 충남: 발효 없음, 서해중부 풍랑 예비특보 + 「충청남도(보령도서)」 강풍 예비특보 → 예비특보
    daecheon = _eval(warn_places["특보-대천"])
    assert daecheon.level == "preliminary"
    assert {p.type for p in daecheon.preliminary} == {"풍랑 예비특보", "강풍 예비특보"}

    # 바다를 알 수 없는 장소 → 「특보 없음」이 아니라 확인 불가
    unknown = _eval(warn_places["특보-미상"])
    assert unknown.level == "unknown" and unknown.reason == "UNKNOWN_SEA"


def test_stale_snapshot_is_unknown(warn_places):
    with SessionLocal() as db:
        for s in db.query(MarineWarningSnapshot).all():
            s.fetched_at = utcnow() - timedelta(hours=4)
        db.commit()
    try:
        assert _eval(warn_places["특보-대천"]).level == "unknown"
    finally:
        with SessionLocal() as db:
            for s in db.query(MarineWarningSnapshot).all():
                s.fetched_at = utcnow()
            db.commit()


def test_conditions_include_warning(client, warn_places):
    from app.core.timeutil import today_kst

    r = client.get(f"/api/v1/places/{warn_places['특보-김녕']}/conditions", params={"date": str(today_kst())})
    w = r.json()["place"]["warning"]
    assert w["level"] == "warning" and w["seas"] == ["제주도"] and w["source"] == "기상청 기상특보"
