"""낚시터 좌표 품질 점검 (읽기 전용 — DB·원본 파일을 바꾸지 않는다).

보고서: docs/03_데이터/2026-11-09_좌표품질_검증보고서.md

입력: DB(낚시터·관측소 연결), 원본 CSV(전국낚시터정보표준데이터, 좌표 원문 글자 그대로)
출력: CSV 한 줄 = 낚시터 한 곳, 요약 출력

사용: python scripts/audit_coordinates.py <낚시터정보.csv> <출력.csv>
"""

import collections
import csv
import io
import math
import re
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import Place, Station  # noqa: E402
from app.models.enums import StationKind  # noqa: E402
from app.services.location import MANUAL_CHECK_IDS, suspect_place_ids  # noqa: E402

CSV_IN, OUT = sys.argv[1], sys.argv[2]


def km(a, b):
    r = math.pi / 180
    h = (
        math.sin((b[0] - a[0]) * r / 2) ** 2
        + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin((b[1] - a[1]) * r / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def decimals(s: str) -> int:
    s = s.strip()
    return len(s.split(".")[1]) if "." in s else 0


def effective(s: str) -> tuple[int, str]:
    """실질 정밀도: 끝자리 0 은 버리고, 분(1/60도)·초 단위 변환값이면 그 단위로 본다"""
    s = s.strip()
    if not s:
        return 9, ""
    v = float(s)
    frac = s.split(".")[1].rstrip("0") if "." in s else ""
    d = len(frac)
    if 3 <= d <= 4 and abs(v * 60 - round(v * 60)) < 0.002 * 60 and abs(v * 60 - round(v * 60)) < 0.02:
        return 2, "분 단위(약 ±0.9km)"
    return d, f"소수 {d}자리"


# 소수 n자리 좌표가 가질 수 있는 최대 반올림 오차 (km, 위도 기준 대략)
UNCERT = {0: 55.0, 1: 5.6, 2: 0.56, 3: 0.06}

raw = open(CSV_IN, "rb").read()
for enc in ("utf-8-sig", "cp949"):
    try:
        text = raw.decode(enc)
        break
    except UnicodeDecodeError:
        continue
src_rows = [r for r in csv.DictReader(io.StringIO(text)) if r["낚시터유형"] == "바다"]
src_by_name = collections.defaultdict(list)
for r in src_rows:
    src_by_name[r["낚시터명"].strip()].append(r)
no_coord = [r for r in src_rows if not r["WGS84위도"].strip() or not r["WGS84경도"].strip()]

SIDO = {
    "서울": "서울특별시",
    "부산": "부산광역시",
    "인천": "인천광역시",
    "울산": "울산광역시",
    "경기": "경기도",
    "강원": "강원",
    "충남": "충청남도",
    "충북": "충청북도",
    "전북": "전북",
    "전남": "전남",
    "경북": "경상북도",
    "경남": "경상남도",
    "제주": "제주",
}
COMMERCIAL = re.compile(r"(슈퍼|횟집|식당|상가|마트|\d+층|호\)|펜션|모텔|민박)")

with SessionLocal() as db:
    places = db.scalars(
        select(Place)
        .where(Place.is_active.is_(True))
        .options(selectinload(Place.region), selectinload(Place.info), selectinload(Place.stations))
        .order_by(Place.id)
    ).all()
    stations = db.scalars(select(Station).where(Station.lat.is_not(None))).all()
    suspects = suspect_place_ids(db)

tides = [s for s in stations if s.kind == StationKind.TIDE]
buoys = [s for s in stations if s.kind == StationKind.BUOY]


def margin(p, cands):
    """가장 가까운 관측소와 두 번째 관측소 거리 차 (좌표 오차가 이보다 크면 연결이 바뀔 수 있다)"""
    ds = sorted(km((p.lat, p.lon), (s.lat, s.lon)) for s in cands)
    return (
        (round(ds[0], 1), round(ds[1] - ds[0], 1))
        if len(ds) >= 2
        else (round(ds[0], 1) if ds else None, None)
    )


coord_groups = collections.defaultdict(list)
for p in places:
    coord_groups[(round(p.lat, 6), round(p.lon, 6))].append(p)

rows = []
for p in places:
    src = p.info.source if p.info else ""
    group = (
        "공공데이터 표준"
        if src.startswith("전국낚시터")
        else "국립해양조사원 지점"
        if src.startswith("국립해양조사원")
        else "수동 지정"
    )
    raw_lat = raw_lon = road = jibun = facility = manager = ""
    if group == "공공데이터 표준":
        cand = [r for r in src_by_name.get(p.name, []) if r["WGS84위도"].strip()]
        # 같은 이름이 여럿이면 좌표가 같은 원본
        r = next(
            (
                c
                for c in cand
                if abs(float(c["WGS84위도"]) - p.lat) < 1e-5 and abs(float(c["WGS84경도"]) - p.lon) < 1e-5
            ),
            cand[0] if cand else None,
        )
        if r:
            raw_lat, raw_lon = r["WGS84위도"].strip(), r["WGS84경도"].strip()
            road, jibun = r["소재지도로명주소"].strip(), r["소재지지번주소"].strip()
            facility, manager = r["수상시설물유형"].strip(), r["관리기관명"].strip()
    dec = (
        min(decimals(raw_lat), decimals(raw_lon))
        if raw_lat
        else min(decimals(repr(p.lat)), decimals(repr(p.lon)))
    )
    if raw_lat:
        (el, nl), (eo, no) = effective(raw_lat), effective(raw_lon)
        if "분 단위" in nl or "분 단위" in no:
            eff, eff_note = 2, "분 단위(약 ±0.9km)"
        else:
            # 위도·경도 중 더 정밀한 쪽 (한쪽이 37.0000 처럼 우연히 0 일 수 있어서)
            eff = max(el, eo)
            eff_note = f"소수 {eff}자리" + (" · 끝자리 0 채움(반올림 의심)" if dec > eff else "")
    else:
        eff, eff_note = dec, f"소수 {dec}자리(기관·수동 좌표)"
    shared = coord_groups[(round(p.lat, 6), round(p.lon, 6))]
    shared_addr_same = len(shared) > 1 and len({(x.info.address if x.info else None) for x in shared}) == 1

    # 도로명·지번 주소의 시·군이 같은지 (원본 안 일치)
    def sg(a):
        parts = a.split()
        return " ".join(parts[:2]) if len(parts) >= 2 else a

    addr_consistent = (
        ""
        if not (road and jibun)
        else (
            "일치" if sg(road).split()[-1] == sg(jibun).split()[-1] else f"불일치({sg(road)} / {sg(jibun)})"
        )
    )

    # 좌표가 주소의 시·군 쪽에 있는지 (대리 지표): 같은 시·군 가장 가까운 곳 vs 다른 시·군 가장 가까운 곳
    others = [
        q
        for q in places
        if q.id != p.id and (round(q.lat, 6), round(q.lon, 6)) != (round(p.lat, 6), round(p.lon, 6))
    ]
    same = [km((p.lat, p.lon), (q.lat, q.lon)) for q in others if q.region_id == p.region_id]
    other = sorted(
        (km((p.lat, p.lon), (q.lat, q.lon)), q.region.name) for q in others if q.region_id != p.region_id
    )
    near_same = round(min(same), 1) if same else None
    near_other_km, near_other_region = (round(other[0][0], 1), other[0][1]) if other else (None, "")
    region_hint = ""
    if (
        near_same is not None
        and near_other_km is not None
        and near_same > 25
        and near_other_km * 3 < near_same
    ):
        region_hint = f"좌표가 {near_other_region} 쪽에 더 가까움(추정)"

    by = {ps.role: ps for ps in p.stations}
    tide_d, tide_margin = margin(p, tides)
    buoy_d, buoy_margin = margin(p, buoys)
    u = (0.93 if "분 단위" in eff_note else UNCERT.get(eff, 0.01)) if eff <= 3 else 0.01
    unstable = []
    if tide_margin is not None and tide_margin < u:
        unstable.append("조위관측소")
    if buoy_margin is not None and buoy_margin < u:
        unstable.append("부이")
    if tide_d is not None and abs(tide_d - 30) < u:
        unstable.append("조위 30km 경계")
    if u >= 2.5:
        unstable.append("예보격자(5km)")

    # 좌표의 의미 (근거가 있을 때만 「추정」, 없으면 확인 불가)
    addr = (p.info.address if p.info else "") or ""
    if p.id in suspects:
        meaning, evidence = (
            "위치 확인 불가",
            "좌표 오류 의심("
            + ("다른 시·도 좌표" if p.id not in MANUAL_CHECK_IDS else "주소와 다른 해역 좌표, 수동 확인")
            + ")",
        )
    elif group == "국립해양조사원 지점":
        meaning = "기관 지정 대표 지점"
        evidence = "국립해양조사원 바다낚시지수 지점 좌표" + (
            " · 이름에 항구 기준 거리 표기(먼바다 선상)" if re.search(r"\(\d+km\)", p.name) else ""
        )
    elif group == "수동 지정":
        meaning, evidence = (
            "항구·해변 대표 위치(추정)",
            "OpenStreetMap 객체 좌표를 수동 지정 — 공신력 자료로 미확인",
        )
    elif shared_addr_same:
        meaning, evidence = "사업장·어촌계 대표 주소(추정)", f"{len(shared)}곳이 같은 주소·같은 좌표"
    elif len(shared) > 1:
        meaning, evidence = "대략적인 지역 좌표(추정)", f"{len(shared)}곳이 같은 좌표(주소는 다름)"
    elif eff <= 2:
        meaning, evidence = "대략적인 지역 좌표(추정)", f"실질 정밀도 {eff_note} (원문 {dec}자리)"
    elif COMMERCIAL.search(addr):
        meaning, evidence = "사업장 주소 가능성", "주소가 상가·업소 형태"
    else:
        meaning, evidence = "확인 불가", "실제 낚시 위치인지 사업장 위치인지 근거 없음"

    # 등급 (A 는 실제 낚시 위치 검증 — 아직 검증한 곳 없음)
    # D 는 근거가 있는 곳만 (대리점검만으로는 의심으로 확정하지 않고 「우선 검토」 표시)
    precise = eff >= 4 and len(shared) == 1
    if p.id in suspects:
        grade, sub = "D", "좌표 오류 의심"
    elif group == "국립해양조사원 지점":
        grade, sub = "B", "기관 대표 지점"
    elif precise:
        grade, sub = "C", "C1 정밀 좌표·의미 미확인"
    else:
        grade, sub = "C", "C2 정밀도 부족(대략·공유 좌표)"
    priority = []
    if p.id in suspects:
        priority.append("좌표 오류 의심")
    if region_hint and p.id not in suspects:
        priority.append(region_hint)
    if COMMERCIAL.search(addr):
        priority.append("주소가 업소 형태")
    if len(shared) > 1 and not shared_addr_same:
        priority.append("다른 주소인데 같은 좌표")

    rows.append(
        {
            "id": p.id,
            "낚시터": p.name,
            "출처구분": group,
            "유형": p.type.value,
            "시군(주소기준)": p.region.name,
            "주소(DB)": addr,
            "도로명주소(원본)": road,
            "지번주소(원본)": jibun,
            "도로명·지번 시군": addr_consistent,
            "수상시설물유형": facility,
            "관리기관": manager,
            "위도(원문)": raw_lat or repr(p.lat),
            "경도(원문)": raw_lon or repr(p.lon),
            "소수자릿수(원문)": dec,
            "실질정밀도": eff_note,
            "최대반올림오차km": u,
            "같은좌표곳수": len(shared),
            "같은좌표·같은주소": "예" if shared_addr_same else "",
            "같은시군 최근접km": near_same,
            "다른시군 최근접km": near_other_km,
            "다른시군 최근접지역": near_other_region,
            "행정구역 대리점검": region_hint,
            "가까운조위관측소km": tide_d,
            "조위 1·2위 차km": tide_margin,
            "연결이 바뀔 수 있음": "·".join(unstable),
            "좌표의미": meaning,
            "근거": evidence,
            "현재 위치확인필요": "예" if p.id in suspects else "",
            "등급": grade,
            "세부": sub,
            "우선검토 사유": " · ".join(priority),
        }
    )

with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

C = collections.Counter
print("전체", len(rows), "| 원본 바다 낚시터", len(src_rows), "좌표 없음(제외)", len(no_coord))
print("출처구분", C(r["출처구분"] for r in rows))
print("등급", sorted(C(r["등급"] for r in rows).items()))
print("등급×출처", sorted(C((r["출처구분"], r["등급"]) for r in rows).items()))
print(
    "공공데이터 소수자릿수",
    sorted(C(r["소수자릿수(원문)"] for r in rows if r["출처구분"] == "공공데이터 표준").items()),
)
print("세부", sorted(C(r["세부"] for r in rows).items()))
print(
    "실질정밀도(공공)", C(r["실질정밀도"] for r in rows if r["출처구분"] == "공공데이터 표준").most_common()
)
print(
    "우선검토",
    [(r["id"], r["낚시터"], r["우선검토 사유"]) for r in rows if r["우선검토 사유"] and r["등급"] != "D"],
)
print("좌표의미", C(r["좌표의미"] for r in rows).most_common())
print(
    "도로명·지번 시군 불일치",
    [
        (r["id"], r["낚시터"], r["도로명·지번 시군"])
        for r in rows
        if r["도로명·지번 시군"].startswith("불일치")
    ],
)
print(
    "행정구역 대리점검 걸림",
    [(r["id"], r["낚시터"], r["행정구역 대리점검"]) for r in rows if r["행정구역 대리점검"]],
)
print(
    "연결이 바뀔 수 있음",
    sum(1 for r in rows if r["연결이 바뀔 수 있음"]),
    C(x for r in rows for x in r["연결이 바뀔 수 있음"].split("·") if x),
)
print("--- 지난 보고의 「소수 1자리 14곳」(DB 숫자 기준) → 원문")
for r in rows:
    if (
        r["출처구분"] == "공공데이터 표준"
        and min(decimals(repr(float(r["위도(원문)"]))), decimals(repr(float(r["경도(원문)"])))) <= 1
    ):
        print(
            " ",
            r["id"],
            r["낚시터"],
            r["시군(주소기준)"],
            r["위도(원문)"],
            r["경도(원문)"],
            "|",
            r["도로명주소(원본)"] or r["지번주소(원본)"],
            "|",
            r["수상시설물유형"],
            "| 같은좌표",
            r["같은좌표곳수"],
            "|",
            r["실질정밀도"],
            "|",
            r["연결이 바뀔 수 있음"],
        )
print("--- 같은 좌표 공유 그룹")
g = collections.defaultdict(list)
for r in rows:
    if r["같은좌표곳수"] > 1:
        g[(r["위도(원문)"], r["경도(원문)"])].append(r)
for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])):
    print(
        " ",
        k,
        len(v),
        v[0]["시군(주소기준)"],
        "같은주소" if v[0]["같은좌표·같은주소"] else "주소 다름",
        [x["id"] for x in v],
    )
print("--- 우선 검토 대상")
for pid in [176, 177, 178, 179, 180, 181, 182, 130, 134]:
    r = next(x for x in rows if x["id"] == pid)
    print(
        " ",
        pid,
        r["낚시터"],
        r["등급"],
        r["위도(원문)"],
        r["경도(원문)"],
        "|",
        r["도로명주소(원본)"],
        "/",
        r["지번주소(원본)"],
        "| 같은시군",
        r["같은시군 최근접km"],
        "다른시군",
        r["다른시군 최근접km"],
        r["다른시군 최근접지역"],
        "|",
        r["좌표의미"],
    )
print("원본 좌표 없음(앱에 없음):", [r["낚시터명"] for r in no_coord])
