"""기상청 기상특보 현황 (공공데이터포털 WthrWrnInfoService/getPwnStatus, DATA_GO_KR_API_KEY).

2026-11-05 실제 응답으로 확인한 형식:
- tmFc: 발표시각 (YYYYMMDDHHmm, KST)
- t6: 발효 중인 특보 — 줄마다 「o 풍랑주의보 : 서해남부북쪽바깥먼바다, 남해동부안쪽먼바다, …」
- t7: 예비특보 — 「(1) 풍랑 예비특보」 머리줄 아래 「o 11월 05일 오전(06시~12시) : 구역, …」
- 구역명 안에 쉼표가 들어갈 수 있다: 「강원도(고성산지, 인제산지)」 → 괄호 안 쉼표는 나누지 않는다
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.clients.khoa import KhoaClient
from app.core.timeutil import KST

URL = "https://apis.data.go.kr/1360000/WthrWrnInfoService/getPwnStatus"


@dataclass
class WarningItem:
    type: str  # 예: 풍랑주의보
    areas: list[str]


@dataclass
class PreliminaryItem:
    type: str  # 예: 풍랑 예비특보
    when: str  # 예: 11월 06일 새벽(00시~06시)
    areas: list[str]


@dataclass
class WarningStatus:
    issued_at: datetime | None
    active: list[WarningItem] = field(default_factory=list)
    preliminary: list[PreliminaryItem] = field(default_factory=list)
    raw_active: str = ""
    raw_preliminary: str = ""


def split_areas(text: str) -> list[str]:
    """쉼표로 나누되 괄호 안 쉼표는 유지"""
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            if cur.strip():
                out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_active(t6: str) -> list[WarningItem]:
    items = []
    for line in (t6 or "").splitlines():
        m = re.match(r"^\s*o\s*(.+?)\s*:\s*(.+)$", line)
        if not m or m.group(1).strip() == "없음":
            continue
        items.append(WarningItem(type=m.group(1).strip(), areas=split_areas(m.group(2))))
    return items


def parse_preliminary(t7: str) -> list[PreliminaryItem]:
    items, current = [], ""
    for line in (t7 or "").splitlines():
        head = re.match(r"^\s*\(\d+\)\s*(.+?)\s*$", line)
        if head:
            current = head.group(1)
            continue
        m = re.match(r"^\s*o\s*(.+?)\s*:\s*(.+)$", line)
        if m and current:
            items.append(
                PreliminaryItem(type=current, when=m.group(1).strip(), areas=split_areas(m.group(2)))
            )
    return items


class KmaWarningClient(KhoaClient):
    """공공데이터포털 공통 호출 로직(KhoaClient._request) 재사용"""

    def status(self) -> WarningStatus:
        items = self._request(URL, {"dataType": "JSON", "numOfRows": 10})
        if not items:
            return WarningStatus(issued_at=None)
        it = items[0]
        tm = str(it.get("tmFc") or "")
        issued = datetime.strptime(tm, "%Y%m%d%H%M").replace(tzinfo=KST) if len(tm) == 12 else None
        t6, t7 = it.get("t6") or "", it.get("t7") or ""
        return WarningStatus(
            issued_at=issued,
            active=parse_active(t6),
            preliminary=parse_preliminary(t7),
            raw_active=t6.strip(),
            raw_preliminary=t7.strip(),
        )
