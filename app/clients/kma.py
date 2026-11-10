"""기상청 단기예보 (공공데이터포털, DATA_GO_KR_API_KEY).

확인된 엔드포인트 (2026-11-05 실제 호출로 검증):
  https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst
  파라미터: base_date, base_time(0200·0500·…·2300), nx, ny, dataType=JSON
  사용 항목: WAV, WSD, TMP, POP, SKY, PTY. 약 5일치 시간별 예보
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.clients.khoa import KhoaClient, _num
from app.core.timeutil import KST

URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
AGENCY = "기상청"
DATASET = "단기예보"

BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
# 발표 후 API 반영까지 여유 (기상청 안내: 발표시각 + 10분 이후 제공)
PUBLISH_DELAY = timedelta(minutes=15)


@dataclass(frozen=True)
class ForecastRow:
    t: datetime
    wave_height_m: float | None
    wind_speed_ms: float | None
    air_temp_c: float | None
    precipitation_probability_pct: float | None
    sky_code: float | None
    precipitation_type_code: float | None


def latest_base_time(now: datetime) -> datetime:
    """now(KST) 기준 조회 가능한 가장 최근 발표 시각"""
    ref = now.astimezone(KST) - PUBLISH_DELAY
    for day_offset in (0, 1):
        d = ref - timedelta(days=day_offset)
        for h in reversed(BASE_HOURS):
            cand = d.replace(hour=h, minute=0, second=0, microsecond=0)
            if cand <= ref:
                return cand
    raise AssertionError("unreachable")


def _value(v) -> float | None:
    """결측(±900 이상) 은 None"""
    x = _num(v)
    return None if x is None or abs(x) >= 900 else x


class KmaForecastClient(KhoaClient):
    """공공데이터포털 공통 호출 로직(KhoaClient._request)을 그대로 쓴다"""

    def short_forecast(self, nx: int, ny: int, base: datetime) -> list[ForecastRow]:
        items = self._request(
            URL,
            {
                "dataType": "JSON",
                "numOfRows": 1500,
                "base_date": base.strftime("%Y%m%d"),
                "base_time": base.strftime("%H%M"),
                "nx": nx,
                "ny": ny,
            },
        )
        by_time: dict[datetime, dict[str, float | None]] = {}
        for i in items:
            cat = i.get("category")
            if cat not in ("WAV", "WSD", "TMP", "POP", "SKY", "PTY"):
                continue
            t = datetime.strptime(i["fcstDate"] + i["fcstTime"], "%Y%m%d%H%M").replace(tzinfo=KST)
            by_time.setdefault(t, {})[cat] = _value(i.get("fcstValue"))
        return [
            ForecastRow(
                t=t,
                wave_height_m=v.get("WAV"),
                wind_speed_ms=v.get("WSD"),
                air_temp_c=v.get("TMP"),
                precipitation_probability_pct=v.get("POP"),
                sky_code=v.get("SKY"),
                precipitation_type_code=v.get("PTY"),
            )
            for t, v in sorted(by_time.items())
        ]
