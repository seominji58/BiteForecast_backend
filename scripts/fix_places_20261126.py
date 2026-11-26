"""출시 전 데이터 점검 반영 (2026-11-26, docs 06_개발환경/2026-11-26_출시전_데이터점검.md, 사용자 승인).

1) 좌표 보정 7곳 — 원본 주소를 카카오 주소 검색(지번·도로명 → 좌표)으로 다시 찾은 값 (육상 기준점, 실제 좌대 위치 아님)
   - 서산 대산읍 화곡리 1891 지선 (우리·항구·백년) → 37.00444, 126.4523  (11/9 보고서의 OSM 추정 37.0043,126.4533 과 일치)
   - 서산 대산읍 화곡리 1845 지선 (만석·김선장·대호) → 37.00116, 126.45915
   - 시락어촌계낚시터(3동) 창원 회진로 1123-25 → 35.07376, 128.4502 (원본 35.04,128.26 은 반올림 좌표)
   보류 유지: 창리해상(마을 중심만 나옴) · 해성(사무실 도로명 주소, 해상 위치와 39km 차이)
2) 비활성 3곳 (places.json 에서 빼면 seeds.load 가 비활성화)
   - 지세포 낚시공원: 같은 이름·주소 시설이 관광정보·공공데이터에 없음
   - 드림바다실내낚시터 · 인천락실내바다낚시터: 실내 시설이라 바다 해황이 의미 없음
3) 좌표 검증 기록 (place_coord_check, batch fix-2026-11-26)
   - 보정 7곳: C · business_address(육상 기준점) · address_location_candidate — 원본 좌표를 근거에 남김
   - 등급 없던 관광정보 낚시터: C · business_address · unverified

실행 (backend):
  python -m scripts.fix_places_20261126              # 미리보기
  python -m scripts.fix_places_20261126 --seeds      # seeds/places.json 고치기
  DATABASE_URL=... python -m seeds.load              # 좌표·관측소 연결 다시 계산 (운영)
  DATABASE_URL=... python -m scripts.fix_places_20261126 --register   # 검증 기록 (운영)
되돌리기: git 으로 places.json 되돌리고 seeds.load · python scripts/coord_checks.py rollback --batch fix-2026-11-26
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

PLACES = Path(__file__).resolve().parent.parent / "seeds" / "places.json"
BATCH = "fix-2026-11-26"

FIX = {
    # 이름: (새 위도, 새 경도, 근거)
    "우리낚시터": (37.00444, 126.4523, "카카오 지번 검색 「충남 서산시 대산읍 화곡리 1891」"),
    "항구낚시터": (37.00444, 126.4523, "카카오 지번 검색 「충남 서산시 대산읍 화곡리 1891」"),
    "백년낚시터": (37.00444, 126.4523, "카카오 지번 검색 「충남 서산시 대산읍 화곡리 1891」"),
    "만석낚시터": (37.00116, 126.45915, "카카오 지번 검색 「충남 서산시 대산읍 화곡리 1845」"),
    "김선장낚시터": (37.00116, 126.45915, "카카오 지번 검색 「충남 서산시 대산읍 화곡리 1845」"),
    "대호낚시터": (37.00116, 126.45915, "카카오 지번 검색 「충남 서산시 대산읍 화곡리 1845」"),
    "시락어촌계낚시터(3동)": (
        35.07376,
        128.4502,
        "카카오 도로명 검색 「경남 창원시 마산합포구 진전면 회진로 1123-25」",
    ),
}
DROP = {"지세포 낚시공원", "드림바다실내낚시터", "인천락실내바다낚시터"}


def fix_seeds(write: bool) -> dict[str, tuple[float, float]]:
    d = json.loads(PLACES.read_text(encoding="utf-8"))
    originals = {}
    for r in d["regions"]:
        keep = []
        for p in r["places"]:
            if p["name"] in DROP:
                print(f"  비활성 {r['name']} · {p['name']}")
                continue
            if p["name"] in FIX:
                lat, lon, why = FIX[p["name"]]
                originals[p["name"]] = (p["lat"], p["lon"])
                print(f"  좌표 {p['name']}: {p['lat']},{p['lon']} → {lat},{lon} ({why})")
                p["lat"], p["lon"] = lat, lon
            keep.append(p)
        r["places"] = keep
    d["regions"] = [r for r in d["regions"] if r["places"]]  # 낚시터가 없어진 지역은 빼서 비활성
    if write:
        PLACES.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("seeds/places.json 저장")
    return originals


ORIG = {
    "우리낚시터": (35.2672, 129.0183),
    "항구낚시터": (35.2672, 129.0183),
    "백년낚시터": (35.2672, 129.0183),
    "만석낚시터": (35.2672, 129.0183),
    "김선장낚시터": (35.2672, 129.0183),
    "대호낚시터": (35.2672, 129.0183),
    "시락어촌계낚시터(3동)": (35.04, 128.26),
}


def register() -> None:
    from sqlalchemy import func, select

    from app.core.db import SessionLocal
    from app.models import Place, PlaceCoordCheck, PlaceInfo

    now = datetime.now(UTC)
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(PlaceCoordCheck).where(PlaceCoordCheck.batch == BATCH)):
            print("이미 등록됨 — 건너뜀")
            return
        graded = set(db.scalars(select(PlaceCoordCheck.place_id).distinct()).all())
        n = 0
        for p in db.scalars(select(Place).where(Place.is_active.is_(True))).all():
            if p.name in FIX:
                o = ORIG[p.name]
                db.add(
                    PlaceCoordCheck(
                        place_id=p.id,
                        grade="C",
                        sub_grade="C2",
                        location_type="business_address",
                        status="address_location_candidate",
                        method="api",
                        checked_by="데이터 점검",
                        checked_at=now,
                        source_ref=FIX[p.name][2],
                        evidence=f"원본 좌표 {o[0]},{o[1]} 가 주소와 어긋나 {FIX[p.name][2]} 좌표로 보정 (육상 기준점, 실제 좌대 위치 아님)",
                        candidate_lat=FIX[p.name][0],
                        candidate_lon=FIX[p.name][1],
                        candidate_note="카카오 주소 검색",
                        batch=BATCH,
                    )
                )
                n += 1
            elif p.id not in graded:
                info = db.get(PlaceInfo, p.id)
                db.add(
                    PlaceCoordCheck(
                        place_id=p.id,
                        grade="C",
                        sub_grade="C2",
                        location_type="business_address",
                        status="unverified",
                        method="desk",
                        checked_by="데이터 점검",
                        checked_at=now,
                        source_ref=(info.source if info else None),
                        evidence="관광정보·공공데이터에 등록된 사업장 위치 (실제 낚시 자리 미확인)",
                        batch=BATCH,
                    )
                )
                n += 1
        db.commit()
        print(f"검증 기록 {n}건 등록 ({BATCH})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", action="store_true")
    ap.add_argument("--register", action="store_true")
    a = ap.parse_args()
    if a.register:
        register()
    else:
        fix_seeds(a.seeds)
