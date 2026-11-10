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


def _set_status(path, value):
    from app.jobs import collector_status

    collector_status.write_status(value, path)


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
    # 적용 해역을 모름은 「다른 해역에만 특보 있음(no_match)」과 다른 상태
    assert unknown.status == "unknown_sea"
    assert _eval(warn_places["특보-김녕"]).status == "active"
    assert daecheon.status == "nearby" and busan.status == "nearby"


def _with_snapshot(active, prelim, fn):
    """잠시 더 최신 스냅샷을 넣고 판정한 뒤 지운다 (테스트용 메모리 DB)"""
    with SessionLocal() as db:
        snap = MarineWarningSnapshot(
            issued_at=utcnow(),
            fetched_at=utcnow() + timedelta(seconds=1),
            active_json=json.dumps(active),
            preliminary_json=json.dumps(prelim),
            raw_active="",
            raw_preliminary="",
        )
        db.add(snap)
        db.commit()
        sid = snap.id
    try:
        return fn()
    finally:
        with SessionLocal() as db:
            db.delete(db.get(MarineWarningSnapshot, sid))
            db.commit()


def test_no_match_vs_no_active_vs_unknown_sea(warn_places):
    jeju_only = [{"type": "풍랑주의보", "areas": ["제주도남쪽먼바다"]}]
    # 다른 해역(제주)에만 특보 → 충남 장소는 no_match (level none 이지만 「특보 없음」과 구분)
    w = _with_snapshot(jeju_only, [], lambda: _eval(warn_places["특보-대천"]))
    assert w.level == "none" and w.status == "no_match"
    # 발표된 해상 특보가 전혀 없음 → no_active_warnings
    w = _with_snapshot([], [], lambda: _eval(warn_places["특보-대천"]))
    assert w.level == "none" and w.status == "no_active_warnings"
    # 해역을 모르는 장소는 특보가 하나도 없어도 「특보 없음」이 아니라 unknown_sea
    w = _with_snapshot([], [], lambda: _eval(warn_places["특보-미상"]))
    assert w.level == "unknown" and w.status == "unknown_sea"


def _make_stale():
    with SessionLocal() as db:
        for s in db.query(MarineWarningSnapshot).all():
            s.fetched_at = utcnow() - timedelta(hours=4)
        db.commit()


def _make_fresh():
    with SessionLocal() as db:
        for s in db.query(MarineWarningSnapshot).all():
            s.fetched_at = utcnow()
        db.commit()


def test_stale_and_warning_collection_failed_together(warn_places, collector_file):
    """자료 만료 + 특보 API 수집 실패가 동시에: 원인은 수집 실패, 문제 목록엔 둘 다"""
    _set_status(collector_file, {
        "state": "partial",
        "stats": {"warning_errors": 1},
        "warning_collection": {"ok": False, "at": utcnow().isoformat()},
    })
    _make_stale()
    try:
        w = _eval(warn_places["특보-대천"])
        assert w.level == "unknown" and w.reason == "NO_DATA"
        assert w.status == "collection_failed"
        assert w.issues == ["stale", "collection_failed"]
    finally:
        _make_fresh()


def test_collector_failure_is_not_warning_failure(warn_places, collector_file):
    """수집기 주기 전체 실패(예: 조위 단계 예외)는 특보 API 실패로 보지 않는다"""
    _set_status(collector_file, {
        "state": "failed",
        "stats": None,
        # 마지막으로 특보를 실제로 호출했던 주기는 성공
        "warning_collection": {"ok": True, "at": (utcnow() - timedelta(hours=5)).isoformat()},
    })
    _make_stale()
    try:
        w = _eval(warn_places["특보-대천"])
        assert w.status == "collector_failed"
        assert w.issues == ["stale", "collector_failed"]
        assert "collection_failed" not in w.issues
    finally:
        _make_fresh()


def test_old_failed_stats_are_not_read_as_current(warn_places, collector_file):
    """이전 형식 상태 파일: 실패 주기에 남은 옛 통계의 warning_errors 는 특보 수집 실패로 보지 않는다"""
    _set_status(collector_file, {"state": "failed", "stats": {"warning_errors": 3}})
    _make_stale()
    try:
        w = _eval(warn_places["특보-대천"])
        assert w.status == "collector_failed" and "collection_failed" not in w.issues
    finally:
        _make_fresh()
    # 정상 종료(partial) 주기의 통계라면 특보 수집 실패
    _set_status(collector_file, {"state": "partial", "stats": {"warning_errors": 1}})
    w = _eval(warn_places["특보-대천"])
    assert w.level == "preliminary" and w.issues == ["collection_failed"]


def test_fresh_snapshot_after_failure_clears_failure(warn_places, collector_file):
    """실패 기록보다 나중에 받은 스냅샷이 있으면 수집 실패로 보지 않는다"""
    _set_status(collector_file, {
        "state": "partial",
        "warning_collection": {"ok": False, "at": (utcnow() - timedelta(hours=1)).isoformat()},
    })
    w = _eval(warn_places["특보-대천"])
    assert w.status == "nearby" and w.issues == []


def test_stale_only(warn_places, collector_file):
    _set_status(collector_file, {
        "state": "success",
        "warning_collection": {"ok": True, "at": utcnow().isoformat()},
    })
    _make_stale()
    try:
        w = _eval(warn_places["특보-대천"])
        assert w.status == "stale" and w.issues == ["stale"]
    finally:
        _make_fresh()


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
