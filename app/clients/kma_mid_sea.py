"""기상청 중기해상예보 (MidFcstInfoService/getMidSeaFcst) — 4~10일 뒤 해역별 파고 범위·날씨.

- 06시·18시(KST) 하루 두 번 발표. 06시 발표는 4일 뒤부터, 18시 발표는 5일 뒤부터 (n일 뒤 = 발표일 + n)
- 4~7일 뒤는 오전·오후(wh{n}AAm/BAm…, wf{n}Am/Pm), 8~10일 뒤는 하루(wh{n}A/B, wf{n})
- whA = 파고 최저, whB = 파고 최고 (m). 해역 단위라 낚시터 지점 값이 아니다
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.clients.khoa import KhoaClient
from app.core.timeutil import KST

URL = "https://apis.data.go.kr/1360000/MidFcstInfoService/getMidSeaFcst"

# 해역 이름 → 기상청 중기해상 구역 코드 (특보 해역 이름과 같은 말을 쓴다)
REGIONS: dict[str, str] = {
    "서해중부": "12A20000",
    "서해남부": "12A30000",
    "남해서부": "12B10000",
    "남해동부": "12B20000",
    "제주도": "12B10500",
    "동해남부": "12C10000",
    "동해중부": "12C20000",
    "동해북부": "12C30000",
}


@dataclass(frozen=True)
class MidSeaRow:
    target_date: date
    period: str  # am · pm · day
    wave_min: float | None
    wave_max: float | None
    weather: str | None


def latest_tm_fc(now: datetime) -> datetime:
    """지금 받을 수 있는 가장 최근 발표 시각 (발표 뒤 15분 여유)"""
    k = now.astimezone(KST)
    for day_offset, hour in ((0, 18), (0, 6), (-1, 18)):
        tm = datetime(k.year, k.month, k.day, hour, tzinfo=KST) + timedelta(days=day_offset)
        if k >= tm + timedelta(minutes=15):
            return tm
    return datetime(k.year, k.month, k.day, 18, tzinfo=KST) - timedelta(days=1)


def _num(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_item(item: dict, tm_fc: datetime) -> list[MidSeaRow]:
    base = tm_fc.astimezone(KST).date()
    rows: list[MidSeaRow] = []
    for n in range(3, 11):
        day = base + timedelta(days=n)
        if f"wh{n}AAm" in item or f"wh{n}BAm" in item:
            for per, sfx in (("am", "Am"), ("pm", "Pm")):
                lo, hi = _num(item.get(f"wh{n}A{sfx}")), _num(item.get(f"wh{n}B{sfx}"))
                wf = item.get(f"wf{n}{sfx}") or None
                if lo is not None or hi is not None or wf:
                    rows.append(MidSeaRow(day, per, lo, hi, wf))
        elif f"wh{n}A" in item or f"wh{n}B" in item:
            lo, hi = _num(item.get(f"wh{n}A")), _num(item.get(f"wh{n}B"))
            wf = item.get(f"wf{n}") or None
            rows.append(MidSeaRow(day, "day", lo, hi, wf))
    return rows


class KmaMidSeaClient(KhoaClient):
    """공공데이터포털 공통 호출 로직(KhoaClient._request) 재사용"""

    def fetch(self, reg_id: str, tm_fc: datetime) -> list[MidSeaRow]:
        tm = tm_fc.astimezone(KST).strftime("%Y%m%d%H%M")
        items = self._request(URL, {"dataType": "JSON", "numOfRows": 10, "regId": reg_id, "tmFc": tm})
        return parse_item(items[0], tm_fc) if items else []
