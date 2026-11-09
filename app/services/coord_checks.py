"""좌표 검증 기록 등록·되돌리기 (보고서 §10 단계 1).

- 원본 좌표(place.lat/lon)는 건드리지 않는다
- 등록은 batch 단위. 같은 batch 를 다시 등록하지 않는다 (중복 방지)
- 되돌리기 = 그 batch 의 기록만 삭제 (다른 기록·낚시터 데이터는 그대로)
"""

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Place, PlaceCoordCheck

REPORT = "docs/03_데이터/2026-11-09_좌표품질_검증보고서.md"

# 감사 CSV 「좌표의미」 → location_type. 「가능성」 수준은 근거가 약해 unknown 으로 둔다
MEANING = {
    "기관 지정 대표 지점": "agency_point",
    "항구·해변 대표 위치(추정)": "harbor",
    "사업장·어촌계 대표 주소(추정)": "business_address",
    "대략적인 지역 좌표(추정)": "approx_area",
    "위치 확인 불가": "unverifiable",
    "사업장 주소 가능성": "unknown",
    "확인 불가": "unknown",
}

# 서산 보정 후보 (docs/03_데이터/2026-11-09_서산_낚시터_좌표_보정_후보.md). 확정 아님 — 육상 기준점
_SAMGILPO = (37.0043, 126.4533)
CANDIDATES = {
    **{
        pid: (
            *_SAMGILPO,
            "삼길포항(OSM) — 화곡리 1891번지(삼길포 선상어시장) 육상 기준점, 실제 좌대 아님 · 신뢰 중간",
        )
        for pid in (177, 181, 182)
    },
    **{
        pid: (*_SAMGILPO, "삼길포항(OSM) — 화곡리 1845번지 위치 미확인, 육상 기준점 · 신뢰 낮음")
        for pid in (178, 179, 180)
    },
}


class RegisterError(Exception):
    pass


def _evidence(r: dict) -> str:
    parts = [r["근거"]]
    if r.get("실질정밀도"):
        parts.append(f"실질 정밀도 {r['실질정밀도']} (원문 {r['위도(원문)']}, {r['경도(원문)']})")
    if int(r.get("같은좌표곳수") or 1) > 1:
        parts.append(
            f"같은 좌표 {r['같은좌표곳수']}곳"
            + (" · 같은 주소" if r.get("같은좌표·같은주소") else " · 주소 다름")
        )
    if r.get("우선검토 사유"):
        parts.append(f"우선 검토: {r['우선검토 사유']}")
    if r.get("행정구역 대리점검"):
        parts.append(f"대리 점검: {r['행정구역 대리점검']}")
    return " / ".join(parts)


def register_from_audit(db: Session, rows: list[dict], batch: str, checked_at: datetime | None = None) -> int:
    """감사 CSV(scripts/audit_coordinates.py 출력) 한 줄 = 기록 하나. 등록한 개수를 돌려준다"""
    if db.scalar(select(func.count(PlaceCoordCheck.id)).where(PlaceCoordCheck.batch == batch)):
        raise RegisterError(f"이미 등록된 batch 입니다: {batch} (되돌린 뒤 다시 등록하세요)")
    if any(r["등급"] == "A" for r in rows):
        # 보고서 기준 A 0곳 — 감사 결과로 A 를 만들지 않는다 (실제 위치 검증은 사람·기관 확인으로만)
        raise RegisterError("감사 결과에 A 등급이 있습니다. A 는 실제 위치 검증으로만 부여합니다")
    known = set(db.scalars(select(Place.id)).all())
    when = checked_at or datetime.now(UTC)
    n = 0
    for r in rows:
        pid = int(r["id"])
        if pid not in known:
            raise RegisterError(f"없는 낚시터 id: {pid}")
        grade = r["등급"]
        sub = r["세부"][:2] if r["세부"].startswith(("C1", "C2")) else None
        status = "needs_review" if grade == "D" or r.get("우선검토 사유") else "unverified"
        cand = CANDIDATES.get(pid)
        db.add(
            PlaceCoordCheck(
                place_id=pid,
                grade=grade,
                sub_grade=sub,
                location_type=MEANING.get(r["좌표의미"], "unknown"),
                status=status,
                method="audit",
                source_ref=REPORT,
                evidence=_evidence(r),
                candidate_lat=cand[0] if cand else None,
                candidate_lon=cand[1] if cand else None,
                candidate_note=cand[2] if cand else None,
                batch=batch,
                checked_by="scripts/audit_coordinates.py",
                checked_at=when,
            )
        )
        n += 1
    db.commit()
    return n


def rollback(db: Session, batch: str) -> int:
    """그 batch 의 기록만 지운다. 원본 좌표·다른 기록은 그대로"""
    n = db.execute(delete(PlaceCoordCheck).where(PlaceCoordCheck.batch == batch)).rowcount
    db.commit()
    return n or 0
