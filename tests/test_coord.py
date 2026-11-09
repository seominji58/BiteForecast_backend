"""좌표 검증 기록 (보고서 docs/03_데이터/2026-11-09_좌표품질_검증보고서.md 단계 0·1)"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.timeutil import today_kst
from app.models import Place, PlaceCoordCheck, Region
from app.services import summary as summary_service
from app.services.coord_checks import RegisterError, register_from_audit, rollback


@pytest.fixture()
def place(client) -> int:
    with SessionLocal() as db:
        r = Region(name="경남 좌표검사시")
        r.places = [Place(name="좌표 검사 좌대", lat=35.04, lon=128.38)]
        db.add(r)
        db.commit()
        return r.places[0].id


def _check(pid: int, grade: str, sub=None, loc="unknown", when=None, batch="t"):
    with SessionLocal() as db:
        db.add(
            PlaceCoordCheck(
                place_id=pid,
                grade=grade,
                sub_grade=sub,
                location_type=loc,
                status="unverified",
                method="manual",
                evidence="테스트",
                batch=batch,
                checked_at=when or datetime.now(UTC),
            )
        )
        db.commit()


def _api_place(client, pid):
    return next(p for p in client.get("/api/v1/places").json() if p["id"] == pid)


def test_no_record_means_not_judged(client, place):
    p = _api_place(client, place)
    assert p["coord"] is None and p["location_suspect"] is False


def test_latest_record_wins_and_history_kept(client, place):
    _check(place, "C", "C2", "business_address", when=datetime.now(UTC) - timedelta(days=1))
    p = _api_place(client, place)
    assert p["coord"]["grade"] == "C" and p["coord"]["approx"] is True
    assert "대략 위치" in p["coord"]["label"] and p["location_suspect"] is False
    # 새 기록(D)을 더하면 현재 상태가 바뀌고, 이전 기록은 남는다
    _check(place, "D", None, "unverifiable")
    p = _api_place(client, place)
    assert p["coord"]["grade"] == "D" and p["location_suspect"] is True
    detail = client.get(f"/api/v1/places/{place}").json()
    assert detail["location_suspect"] is True and detail["coord"]["label"] == "위치 확인 필요"
    with SessionLocal() as db:
        assert db.scalar(select(func.count(PlaceCoordCheck.id)).where(PlaceCoordCheck.place_id == place)) == 2
        # 원본 좌표는 그대로
        assert (db.get(Place, place).lat, db.get(Place, place).lon) == (35.04, 128.38)

    # D 등급: 해황 연결·요약에서 위치 확인 필요로 처리 (자료를 정상처럼 보여주지 않음)
    day = str(today_kst())
    pc = client.get(f"/api/v1/places/{place}/conditions", params={"date": day}).json()["place"]
    assert pc["warning"]["reason"] == "LOCATION_CHECK"
    assert all(s["status"] == "unavailable" for s in pc["series"])
    summary_service._cache.clear()
    s = next(
        x for x in client.get(f"/api/v1/places-summary?date={day}").json()["places"] if x["place_id"] == place
    )
    assert s["location_suspect"] is True and s["wave_fc_max"] is None


def test_register_and_rollback(client, place):
    row = {
        "id": str(place),
        "등급": "C",
        "세부": "C2 정밀도 부족(대략·공유 좌표)",
        "좌표의미": "사업장·어촌계 대표 주소(추정)",
        "근거": "17곳이 같은 주소·같은 좌표",
        "실질정밀도": "소수 2자리",
        "위도(원문)": "35.04",
        "경도(원문)": "128.38",
        "같은좌표곳수": "17",
        "같은좌표·같은주소": "예",
        "우선검토 사유": "",
        "행정구역 대리점검": "",
    }
    with SessionLocal() as db:
        assert register_from_audit(db, [row], "audit-test") == 1
        with pytest.raises(RegisterError):
            register_from_audit(db, [row], "audit-test")  # 같은 batch 중복 등록 거부
        with pytest.raises(RegisterError):
            register_from_audit(db, [{**row, "등급": "A"}], "audit-test-2")  # 감사로 A 를 만들지 않음
        c = db.scalar(select(PlaceCoordCheck).where(PlaceCoordCheck.batch == "audit-test"))
        assert (c.grade, c.sub_grade, c.location_type, c.method) == ("C", "C2", "business_address", "audit")
        assert "같은 좌표 17곳" in c.evidence
        assert rollback(db, "audit-test") == 1
        assert (
            db.scalar(select(func.count(PlaceCoordCheck.id)).where(PlaceCoordCheck.batch == "audit-test"))
            == 0
        )
        assert db.get(Place, place) is not None


def test_d_grade_place_in_trip_has_no_location_data(client, place):
    """D등급 낚시터도 출조계획에는 넣을 수 있지만, 위치·해황을 정상처럼 주지 않는다"""
    from tests.conftest import signup

    _check(place, "D", None, "unverifiable")
    h = signup(client)
    day = str(today_kst() + timedelta(days=1))
    t = client.post(
        "/api/v1/me/trips",
        json={"start_date": day, "end_date": day, "stops": [{"day": day, "place_id": place}]},
        headers=h,
    ).json()
    stop = t["stops"][0]
    assert stop["place"]["location_suspect"] is True and stop["place"]["coord"]["grade"] == "D"
    o = client.get(f"/api/v1/me/trips/{t['id']}/outlook", headers=h).json()["stops"][0]
    assert o["forecast_status"] == "location_check"
    assert (
        o["wave_fc_max"] is None
        and o["wind_fc_max"] is None
        and o["tides"] == []
        and o["warning_level"] is None
    )


def test_address_batch_keeps_grade_and_holds_recommendation(client, place):
    from app.services.coord_checks import register_address_batch

    _check(place, "C", "C1", "unknown")
    row = {
        "id": str(place),
        "출처구분": "공공데이터 표준",
        "행안부 검색 상태": "검색됨",
        "VWorld 도로명 상태": "검색됨",
        "VWorld 지번 상태": "검색됨",
        "대조상태": "대조 완료",
        "원본 좌표 위치": "다른 시군",
        "위치 유형(추정)": "원본 좌표가 주소와 다른 시·군 — 오류 가능성 높음",
        "기존등급 변경 후보": "D 후보",
    }
    with SessionLocal() as db:
        with pytest.raises(RegisterError):
            register_address_batch(db, [{**row, "판정 거리 km": "17.6"}], "addr-test")  # 거리 값 든 CSV 거부
        assert register_address_batch(db, [row], "addr-test") == 2  # 행안부·VWorld 기록 각각
        with pytest.raises(RegisterError):
            register_address_batch(db, [row], "addr-test")  # 같은 배치 중복 거부
        recs = db.scalars(select(PlaceCoordCheck).where(PlaceCoordCheck.batch == "addr-test")).all()
        assert {r.method for r in recs} == {"juso", "vworld"}
        assert all((r.grade, r.sub_grade, r.status) == ("C", "C1", "coord_mismatch_suspected") for r in recs)
        assert all(r.candidate_lat is None for r in recs)  # 좌표 저장 안 함
    p = _api_place(client, place)
    # 등급은 그대로(C), 추천 보류 + 대략 위치 취급, 위치 확인 필요(D)는 아님
    assert (
        p["coord"]["grade"] == "C" and p["coord"]["recommend_hold"] is True and p["coord"]["approx"] is True
    )
    assert p["location_suspect"] is False and "좌표 불일치 의심" in p["coord"]["label"]


def test_review_hold_place_withholds_coordinate_data_but_keeps_address_warning(client, place):
    """좌표 불일치 의심: C등급 유지, 좌표 기준 해황은 판단 보류, 특보는 주소 기준 + 안내"""
    from tests.conftest import signup

    with SessionLocal() as db:
        db.add(
            PlaceCoordCheck(
                place_id=place,
                grade="C",
                location_type="unknown",
                status="coord_mismatch_suspected",
                method="vworld",
                evidence="테스트",
                batch="t-hold",
            )
        )
        db.commit()
    day = str(today_kst())
    pc = client.get(f"/api/v1/places/{place}/conditions", params={"date": day}).json()["place"]
    assert all(s["status"] == "unavailable" and s["reason"] == "LOCATION_REVIEW" for s in pc["series"])
    assert pc["fishing_index"]["reason"] == "LOCATION_REVIEW"
    assert pc["warning"]["reason"] != "LOCATION_CHECK" and pc["warning"]["basis"] == "address"
    assert pc["warning"]["reference_only"] is True and "참고용" in pc["warning"]["note"]
    assert "실제 낚시 위치에 적용되는 특보는 아직 확인되지 않았어요" in pc["warning"]["note"]
    assert pc["place"]["coord"]["grade"] == "C" and pc["place"]["location_suspect"] is False

    summary_service._cache.clear()
    s = next(
        x for x in client.get(f"/api/v1/places-summary?date={day}").json()["places"] if x["place_id"] == place
    )
    assert s["wave_fc_max"] is None and s["wind_fc_max"] is None and s["next_tide"] is None

    h = signup(client)
    t = client.post(
        "/api/v1/me/trips",
        json={"start_date": day, "end_date": day, "stops": [{"day": day, "place_id": place}]},
        headers=h,
    ).json()
    o = client.get(f"/api/v1/me/trips/{t['id']}/outlook", headers=h).json()["stops"][0]
    assert o["forecast_status"] == "location_review" and o["wave_fc_max"] is None and o["tides"] == []
    assert o["warning_note"] and o["warning_is_current"] is True


def test_reference_warning_never_says_none(client, place):
    """주소 기준으로 특보가 없어도 「특보 없음」이 아니라 「확인 불가(참고)」. 수집이 오래되면 확인 불가"""

    from app.models import MarineWarningSnapshot
    from app.models.base import utcnow

    _check(place, "C", None, "unknown")
    with SessionLocal() as db:
        db.add(
            PlaceCoordCheck(
                place_id=place,
                grade="C",
                location_type="unknown",
                status="coord_mismatch_suspected",
                method="vworld",
                evidence="테스트",
                batch="t-ref",
            )
        )
        snap = MarineWarningSnapshot(
            issued_at=utcnow(),
            fetched_at=utcnow(),
            active_json="[]",
            preliminary_json="[]",
            raw_active="",
            raw_preliminary="",
        )
        db.add(snap)
        db.commit()
        snap_id = snap.id
    try:
        day = str(today_kst())
        w = client.get(f"/api/v1/places/{place}/conditions", params={"date": day}).json()["place"]["warning"]
        assert w["address_level"] == "none" and w["level"] == "unknown" and w["reason"] == "LOCATION_REVIEW"
        summary_service._cache.clear()
        s = next(
            x
            for x in client.get(f"/api/v1/places-summary?date={day}").json()["places"]
            if x["place_id"] == place
        )
        assert s["warning_level"] == "unknown"  # 지도·목록에도 「특보 없음」으로 나오지 않음
    finally:
        with SessionLocal() as db:
            db.delete(db.get(MarineWarningSnapshot, snap_id))
            db.commit()
        summary_service._cache.clear()
