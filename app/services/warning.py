"""장소별 해상 특보 판정 (명세 UX 검토 P0-1).

기상청 특보 구역명은 「서해중부안쪽먼바다」「동해중부앞바다」처럼 큰 바다 단위이고,
일부 육상·도서 특보는 「전라남도(흑산도.홍도)」처럼 도 단위로 온다.
장소를 한 구역에 정확히 매핑하지 않고, 「속한 바다 + 도 이름」 키워드로 넓게 맞춘다.
→ 실제보다 넓게 경고할 수는 있어도 경고를 놓치지 않는 쪽으로 설계한다.

등급
- warning     : 앞바다(연안)·도 단위 해상 특보, 또는 선상 포인트에 걸린 먼바다 특보
- nearby      : 같은 바다의 먼바다 특보만 있음(연안 장소), 또는 같은 도의 강풍 등 육상·도서 특보
- preliminary : 발효 특보는 없고 예비특보가 걸림
- none        : 최근 3시간 안에 받은 특보 현황에서 해당 없음
- unknown     : 특보 자료가 없거나 오래됨, 또는 장소의 바다를 알 수 없음 → 「특보 없음」으로 표시하지 않는다
"""

import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MarineWarningSnapshot, Place
from app.models.base import utcnow
from app.models.enums import PlaceType
from app.schemas.compare import WarningMatchOut, WarningOut

STALE_AFTER = timedelta(hours=3)
MARINE_TYPES = ("풍랑", "폭풍해일", "태풍", "해일")

# 도(시·도 약칭) → 속한 바다. 도 이름 자체도 키워드로 쓴다
SIDO_SEA = {
    "강원": ["동해중부"],
    "경북": ["동해남부"],
    "울산": ["동해남부"],
    "부산": ["남해동부", "동해남부"],
    "경남": ["남해동부"],
    "전북": ["서해남부"],
    "충남": ["서해중부"],
    "경기": ["서해중부"],
    "인천": ["서해중부"],
    "제주": ["제주도"],
}
SIDO_FULL = {
    "강원": "강원도",
    "경북": "경상북도",
    "울산": "울산",
    "부산": "부산",
    "경남": "경상남도",
    "전남": "전라남도",
    "전북": "전라북도",
    "충남": "충청남도",
    "경기": "경기도",
    "인천": "인천",
    "제주": "제주도",
}
# 전남은 서해 쪽과 남해 쪽이 나뉜다
JEONNAM_WEST = {"신안군", "무안군", "목포시", "영광군", "함평군"}
JEONNAM_BOTH = {"진도군"}


def sea_keywords(place: Place) -> tuple[list[str], str | None]:
    """(바다 키워드, 시·도 약칭). 알 수 없으면 ([], None)"""
    parts = place.region_name.split()
    sido = parts[0] if parts else None
    sigungu = parts[1] if len(parts) > 1 else ""
    if sido == "전남":
        seas = (
            ["서해남부"]
            if sigungu in JEONNAM_WEST
            else ["남해서부", "서해남부"]
            if sigungu in JEONNAM_BOTH
            else ["남해서부"]
        )
    else:
        seas = SIDO_SEA.get(sido or "", [])
    if place.name.startswith("울릉") or sigungu == "울릉군":
        seas = [*seas, "울릉도"]
    return seas, (sido if seas else None)


def _matches(area: str, seas: list[str], sido: str) -> bool:
    return any(s in area for s in seas) or sido in area or SIDO_FULL.get(sido, "@") in area


def evaluate(db: Session, place: Place) -> WarningOut:
    snap = db.scalar(select(MarineWarningSnapshot).order_by(MarineWarningSnapshot.fetched_at.desc()).limit(1))
    seas, sido = sea_keywords(place)
    base = {
        "seas": seas,
        "issued_at": snap.issued_at if snap else None,
        "fetched_at": snap.fetched_at if snap else None,
    }

    if snap is None or utcnow() - snap.fetched_at > STALE_AFTER:
        return WarningOut(level="unknown", reason="NO_DATA", **base)
    if not seas or sido is None:
        return WarningOut(level="unknown", reason="UNKNOWN_SEA", **base)

    active = json.loads(snap.active_json)
    prelim = json.loads(snap.preliminary_json)
    is_boat = place.type == PlaceType.BOAT

    matched: list[WarningMatchOut] = []
    level = "none"
    for w in active:
        areas = [a for a in w["areas"] if _matches(a, seas, sido)]
        if not areas:
            continue
        marine = any(t in w["type"] for t in MARINE_TYPES)
        coastal = any("앞바다" in a or "전해상" in a for a in areas) or any(
            sido in a or SIDO_FULL.get(sido, "@") in a for a in areas
        )
        severe = marine and (coastal or is_boat)
        matched.append(WarningMatchOut(type=w["type"], areas=areas, when=None, severe=severe))
        if severe:
            level = "warning"
        elif level != "warning":
            level = "nearby"

    prelim_matched = [
        WarningMatchOut(
            type=p["type"],
            areas=[a for a in p["areas"] if _matches(a, seas, sido)],
            when=p["when"],
            severe=False,
        )
        for p in prelim
        if any(_matches(a, seas, sido) for a in p["areas"])
    ]
    if level == "none" and prelim_matched:
        level = "preliminary"

    return WarningOut(level=level, active=matched, preliminary=prelim_matched, **base)
