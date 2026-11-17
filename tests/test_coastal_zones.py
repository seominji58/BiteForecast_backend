"""해양경찰청 출입통제·연안사고 위험구역 — 대표 규제 상태와 지도 안내"""

from app.core.db import SessionLocal
from app.core.timeutil import today_kst
from app.models import Place, Region, Restriction
from app.models.enums import RegulationStatus, RestrictionType
from app.services import summary as summary_service


def _place(name: str) -> int:
    with SessionLocal() as db:
        r = Region(name=f"충남 구역시험 {name}")
        r.places = [Place(name=name, lat=36.3, lon=126.5)]
        db.add(r)
        db.commit()
        return r.places[0].id


def _add(pid, rtype, status, remarks):
    with SessionLocal() as db:
        db.add(Restriction(place_id=pid, restriction_type=rtype, status=status, remarks=remarks, geometry_accuracy="high"))
        db.commit()


def _summary(client, pid):
    summary_service._cache.clear()
    rows = client.get(f"/api/v1/places-summary?date={today_kst()}").json()["places"]
    return next(x for x in rows if x["place_id"] == pid)


def test_danger_zone_is_warning_not_ban(client):
    pid = _place("위험구역 방파제")
    _add(pid, RestrictionType.COASTAL_DANGER, RegulationStatus.UNVERIFIED, "○○항 방파제 (방파제(TTP)) · 안에 있음")
    reg = client.get(f"/api/v1/places/{pid}/regulation", params={"date": str(today_kst())}).json()
    assert reg["status"] == "UNVERIFIED"  # 위험구역만으로 금지·조건부가 되지 않는다
    assert reg["items"][0]["remarks"].startswith("○○항 방파제")
    assert _summary(client, pid)["zone_notes"] == ["연안사고 위험구역"]


def test_control_zone_inside_is_conditional(client):
    pid = _place("통제구역 안")
    _add(pid, RestrictionType.ACCESS, RegulationStatus.CONDITIONAL, "구봉도 주변 해상 · 안에 있음")
    _add(pid, RestrictionType.COASTAL_DANGER, RegulationStatus.UNVERIFIED, "구봉도 · 113m 근처")
    reg = client.get(f"/api/v1/places/{pid}/regulation", params={"date": str(today_kst())}).json()
    assert reg["status"] == "CONDITIONAL"
    assert _summary(client, pid)["zone_notes"] == ["출입통제구역 공고 범위 안", "연안사고 위험구역 근처"]
