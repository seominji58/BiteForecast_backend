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


# --- 주소 API 대조 배치 (보고서 docs/03_데이터/2026-11-10_주소API_좌표대조_보고서.md) ---

ADDRESS_REPORT = "docs/03_데이터/2026-11-10_주소API_좌표대조_보고서.md"


def _latest(db: Session) -> dict[int, PlaceCoordCheck]:
    latest = (
        select(PlaceCoordCheck.place_id, func.max(PlaceCoordCheck.id).label("mid"))
        .group_by(PlaceCoordCheck.place_id)
        .subquery()
    )
    return {
        c.place_id: c
        for c in db.scalars(select(PlaceCoordCheck).join(latest, PlaceCoordCheck.id == latest.c.mid))
    }


def register_address_batch(
    db: Session, rows: list[dict], batch: str, checked_at: datetime | None = None
) -> int:
    """주소 대조 결과(--public CSV)를 검증 이력으로 추가한다.

    - 등급·세부 등급·위치 유형은 직전 기록을 그대로 복사한다 (이번 단계에서 등급 변경 없음)
    - 내부 검토 상태만 바꾼다: D 후보 → coord_mismatch_suspected, B 후보 → address_location_candidate,
      우선 확인 → needs_review, 나머지는 직전 상태 유지
    - 출처별로 기록을 나눈다: method=juso (행정안전부 검색 상태), method=vworld (VWorld 검색 상태·판정)
    - VWorld 가 돌려준 주소·좌표와 거리 값은 저장하지 않는다 (입력 CSV 에도 없음)
    """
    if db.scalar(select(func.count(PlaceCoordCheck.id)).where(PlaceCoordCheck.batch == batch)):
        raise RegisterError(f"이미 등록된 batch 입니다: {batch}")
    banned = ("km", "원본↔", "판정 거리")
    if rows and any(k for k in rows[0] if any(b in k for b in banned)):
        raise RegisterError("거리 값이 든 CSV 입니다. --public 으로 만든 CSV 만 등록합니다")
    prev = _latest(db)
    when = checked_at or datetime.now(UTC)
    n = 0
    for r in rows:
        if r["출처구분"] != "공공데이터 표준":
            continue  # 주소가 없어 API 를 부르지 않은 곳 (기관 지점·수동 지정)
        pid = int(r["id"])
        p = prev.get(pid)
        if p is None:
            raise RegisterError(f"기존 검증 이력이 없는 낚시터: {pid}")
        cand = r["기존등급 변경 후보"]
        if cand == "D 후보":
            status = "coord_mismatch_suspected"
        elif cand.startswith("B 후보"):
            status = "address_location_candidate"
        elif "우선 확인" in cand:
            status = "needs_review"
        else:
            status = p.status
        common = dict(
            place_id=pid,
            grade=p.grade,
            sub_grade=p.sub_grade,
            location_type=p.location_type,
            status=status,
            source_ref=ADDRESS_REPORT,
            batch=batch,
            checked_by="scripts/verify_addresses.py",
            checked_at=when,
        )
        db.add(
            PlaceCoordCheck(
                **common, method="juso", evidence=f"행정안전부 도로명주소 검색: {r['행안부 검색 상태']}"
            )
        )
        db.add(
            PlaceCoordCheck(
                **common,
                method="vworld",
                evidence=(
                    f"VWorld 지오코딩 — 도로명: {r['VWorld 도로명 상태']} / 지번: {r['VWorld 지번 상태']}"
                    f" · 대조 상태: {r['대조상태']} · 원본 좌표 위치: {r['원본 좌표 위치']}"
                    f" · 판정(추정): {r['위치 유형(추정)']} · 등급 후보: {cand} (등급 변경 안 함)"
                    " · VWorld 주소·좌표·거리는 저장하지 않음"
                ),
            )
        )
        n += 2
    db.commit()
    return n
