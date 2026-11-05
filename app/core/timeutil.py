from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def today_kst() -> date:
    return datetime.now(KST).date()


def kst_day_range(day: date) -> tuple[datetime, datetime]:
    """KST 기준 하루 [00:00, 다음날 00:00)"""
    start = datetime.combine(day, time(0), KST)
    return start, start + timedelta(days=1)


def parse_kst(s: str) -> datetime:
    """공공 API 의 'YYYY-MM-DD HH:MM[:SS]' (KST, 시간대 표기 없음) → tz-aware"""
    s = s.strip()
    fmt = "%Y-%m-%d %H:%M:%S" if s.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(s, fmt).replace(tzinfo=KST)
