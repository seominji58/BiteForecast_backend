"""해양경찰청 연안 출입통제구역·연안사고 위험구역(공간정보) → 낚시터별 restriction (2026-11-17).

    .venv/bin/python -m scripts.import_coastal_zones            # 미리보기 (DB 를 바꾸지 않음)
    .venv/bin/python -m scripts.import_coastal_zones --apply    # restriction 에 넣기 (같은 출처 행은 지우고 다시)

- 입력: 06_개발환경/data_raw/ 의 공공데이터포털 zip 두 개 (WGS84 경위도 Shapefile, 파일명 CP949)
- 낚시터 좌표가 구역 「안」이거나 300m 이내인 것만 넣는다
- 출입통제구역 안 → CONDITIONAL(공고 확인 필요). 「금지」로 단정하지 않는다 — 도형이 넓게 그려졌을 수 있고 허가 시설도 있다
- 출입통제구역 근처·연안사고 위험구역 → UNVERIFIED (경고 정보, 대표 규제 상태를 바꾸지 않음)
- 표준 라이브러리만 쓴다 (Shapefile 직접 해석)
"""

import argparse
import io
import math
import struct
import zipfile
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.models import Place, Restriction
from app.models.base import utcnow
from app.models.enums import RegulationStatus, RestrictionType

RAW = Path(__file__).resolve().parents[2] / "06_개발환경" / "data_raw"
NEAR_M = 300
SOURCES = {
    "control": {
        "zip": "해양경찰청_연안 출입통제구역 현황_20230501.zip",
        "enc": "cp949",
        "label": "해양경찰청 연안 출입통제구역 현황(2023-05-01) 공간정보",
        "published": date(2023, 5, 1),
    },
    "danger": {
        "zip": "해양경찰청_연안위험구역현황_20230101.zip",
        "enc": "utf-8",
        "label": "해양경찰청 연안위험구역현황(2023-01-01) 공간정보",
        "published": date(2023, 1, 1),
    },
}


def _members(zpath: Path) -> dict[str, bytes]:
    out = {}
    with zipfile.ZipFile(zpath) as zf:
        for info in zf.infolist():
            ext = Path(info.filename).suffix.lower()
            if ext:
                out[ext] = zf.read(info)
    return out


def _dbf(b: bytes, enc: str) -> list[list[str]]:
    n, hl, rl = struct.unpack("<IHH", b[4:12])
    lens, i = [], 32
    while b[i] != 0x0D:
        lens.append(b[i + 16])
        i += 32
    rows = []
    for r in range(n):
        off, row = hl + r * rl + 1, []
        for ln in lens:
            row.append(b[off : off + ln].decode(enc, "replace").strip())
            off += ln
        rows.append(row)
    return rows


def _polygons(b: bytes) -> list[list[list[tuple[float, float]]]]:
    i, polys = 100, []
    while i < len(b):
        _, clen = struct.unpack(">ii", b[i : i + 8])
        i += 8
        rec = b[i : i + clen * 2]
        i += clen * 2
        if struct.unpack("<i", rec[:4])[0] != 5:
            polys.append([])
            continue
        np_, npt = struct.unpack("<ii", rec[36:44])
        parts = list(struct.unpack(f"<{np_}i", rec[44 : 44 + 4 * np_]))
        base = 44 + 4 * np_
        pts = [struct.unpack("<dd", rec[base + 16 * j : base + 16 * j + 16]) for j in range(npt)]
        polys.append([pts[parts[k] : (parts[k + 1] if k + 1 < np_ else npt)] for k in range(np_)])
    return polys


def _inside(x: float, y: float, rings) -> bool:
    c = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                c = not c
    return c


def _dist_m(x: float, y: float, rings) -> float:
    kx, ky, best = 111320 * math.cos(math.radians(y)), 110540, math.inf
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
            ax, ay, bx, by = (x1 - x) * kx, (y1 - y) * ky, (x2 - x) * kx, (y2 - y) * ky
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy
            t = 0 if ll == 0 else max(0, min(1, -(ax * dx + ay * dy) / ll))
            best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def compute(places: list[Place]) -> list[dict]:
    rows = []
    for tag, src in SOURCES.items():
        m = _members(RAW / src["zip"])
        polys, attrs = _polygons(m[".shp"]), _dbf(m[".dbf"], src["enc"])
        for p in places:
            if p.lat is None or p.lon is None:
                continue
            best = None
            for poly, a in zip(polys, attrs, strict=False):
                if not poly:
                    continue
                d = 0.0 if _inside(p.lon, p.lat, poly) else _dist_m(p.lon, p.lat, poly)
                if best is None or d < best[0]:
                    best = (d, a)
            if best is None or best[0] > NEAR_M:
                continue
            d, a = best
            where = "안에 있음" if d == 0 else f"{round(d)}m 근처"
            if tag == "control":
                # num, pname, name, place_type, plave_type, address, announcement
                rows.append(dict(
                    place=p, type=RestrictionType.ACCESS,
                    status=RegulationStatus.CONDITIONAL if d == 0 else RegulationStatus.UNVERIFIED,
                    authority="해양경찰청", notice_no=a[6] or None,
                    remarks=f"{a[2]} ({a[4]}) · {where} · 현장 안내와 해경 공고를 확인하세요",
                    src=src,
                ))
            else:
                # name, 소속서, 관할파출소, 구역분류, 장소명, 장소형태, 주소
                rows.append(dict(
                    place=p, type=RestrictionType.COASTAL_DANGER, status=RegulationStatus.UNVERIFIED,
                    authority=f"해양경찰청 {a[1]}".strip(), notice_no=None,
                    remarks=f"{a[4]} ({a[5]}) · {where} · 연안사고 위험구역 — 현장 안전수칙을 확인하세요",
                    src=src,
                ))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    with SessionLocal() as db:
        places = list(db.scalars(select(Place).where(Place.is_active.is_(True))).all())
        rows = compute(places)
        for r in rows:
            print(f"{r['type'].value:15} {r['status'].value:11} {r['place'].name} ({r['place'].region_name}) — {r['remarks']}")
        print(f"합계 {len(rows)}건 (출입통제 {sum(r['type'] == RestrictionType.ACCESS for r in rows)}, "
              f"위험구역 {sum(r['type'] == RestrictionType.COASTAL_DANGER for r in rows)})")
        if not args.apply:
            print("미리보기만 했어요 (--apply 로 넣기)")
            return
        labels = [s["label"] for s in SOURCES.values()]
        db.execute(delete(Restriction).where(Restriction.geometry_source.in_(labels)))
        now = utcnow()
        for r in rows:
            db.add(Restriction(
                place_id=r["place"].id, restriction_type=r["type"], status=r["status"],
                authority=r["authority"], legal_basis="연안사고 예방에 관한 법률", notice_no=r["notice_no"],
                geometry_source=r["src"]["label"], geometry_accuracy="high",
                published_at=r["src"]["published"], verified_at=date.today(), last_checked_at=now,
                update_state="ok", remarks=r["remarks"][:2000],
            ))
        db.commit()
        print("넣었어요")


if __name__ == "__main__":
    main()
