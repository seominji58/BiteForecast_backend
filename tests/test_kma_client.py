"""기상청 단기예보 클라이언트 테스트 (실제 응답 형식 기반, 네트워크 미사용)"""

from datetime import datetime

import httpx

from app.clients.kma import KmaForecastClient, latest_base_time
from app.core.kma_grid import latlon_to_grid
from app.core.timeutil import KST


def item(cat: str, date: str, time: str, value: str) -> dict:
    return {
        "baseDate": "20261105",
        "baseTime": "0500",
        "category": cat,
        "fcstDate": date,
        "fcstTime": time,
        "fcstValue": value,
        "nx": 88,
        "ny": 141,
    }


# 2026-11-05 실제 응답 형식 (response 로 한 번 더 감싸져 있음)
OK = {
    "response": {
        "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
        "body": {
            "dataType": "JSON",
            "items": {
                "item": [
                    item("TMP", "20261105", "0600", "10"),
                    item("WSD", "20261105", "0600", "1.4"),
                    item("WAV", "20261105", "0600", "0.5"),
                    item("WSD", "20261105", "0700", "2.0"),
                    item("WAV", "20261105", "0700", "-999"),  # 결측
                ]
            },
            "totalCount": 5,
        },
    }
}


def test_short_forecast_parses_wav_wsd_and_missing():
    c = KmaForecastClient(
        api_key="test",
        http=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=OK))),
    )
    c.min_interval = 0
    rows = c.short_forecast(88, 141, datetime(2026, 11, 5, 5, tzinfo=KST))
    assert [r.t.hour for r in rows] == [6, 7]
    assert rows[0].wave_height_m == 0.5 and rows[0].wind_speed_ms == 1.4
    assert rows[1].wave_height_m is None  # -999 → 자료 없음
    assert rows[0].t.utcoffset().total_seconds() == 9 * 3600


def test_latest_base_time():
    def at(h, m):
        return datetime(2026, 11, 5, h, m, tzinfo=KST)

    assert latest_base_time(at(5, 20)).hour == 5  # 발표 15분 뒤부터 사용
    assert latest_base_time(at(5, 10)).hour == 2
    prev = latest_base_time(at(1, 0))  # 02시 발표 전 → 전날 23시
    assert (prev.day, prev.hour) == (4, 23)


def test_grid_matches_kma_reference():
    # 기상청 격자 예: 서울 종로구 (60, 127)
    assert latlon_to_grid(37.5729, 126.9794) == (60, 127)
