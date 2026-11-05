"""국립해양조사원 클라이언트 응답 해석 테스트 (실제 응답 형식 기반, 네트워크 미사용)"""

from datetime import date

import httpx
import pytest

from app.clients.khoa import KhoaClient, KhoaError
from app.models.enums import TideExtremeType

# 2026-11-05 실제 응답에서 발췌
TIDE_EXTREME_OK = {
    "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
    "body": {
        "items": {
            "item": [
                {
                    "obsvtrNm": "군산",
                    "lot": 126.56305,
                    "lat": 35.97555,
                    "predcDt": "2026-11-05 06:34",
                    "predcTdlvVl": 164.0,
                    "extrSe": "2",
                },
                {
                    "obsvtrNm": "군산",
                    "lot": 126.56305,
                    "lat": 35.97555,
                    "predcDt": "2026-11-05 12:23",
                    "predcTdlvVl": 546.0,
                    "extrSe": "3",
                },
            ]
        },
        "pageNo": 1,
        "numOfRows": 10,
        "totalCount": 2,
        "type": "json",
    },
}
BUOY_OK = {
    "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
    "body": {
        "items": {
            "item": [
                {
                    "obsvtrNm": "경포대해수욕장",
                    "obsrvnDt": "2026-11-05 12:00",
                    "wspd": 4.2,
                    "wvhgt": 0.2,
                    "wtem": None,
                },
                {
                    "obsvtrNm": "경포대해수욕장",
                    "obsrvnDt": "2026-11-05 11:00",
                    "wspd": 3.5,
                    "wvhgt": 0.0,
                    "wtem": 15.89,
                },
            ]
        }
    },
}
NOT_REGISTERED = {
    "OpenAPI_ServiceResponse": {
        "cmmMsgHeader": {
            "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
            "returnAuthMsg": "등록되지 않은 서비스키",
            "returnReasonCode": "30",
        }
    }
}


def client_with(status: int, body: dict) -> KhoaClient:
    transport = httpx.MockTransport(lambda req: httpx.Response(status, json=body))
    c = KhoaClient(api_key="test", http=httpx.Client(transport=transport))
    c.min_interval = 0
    return c


def test_tide_extremes_parsed_as_kst_and_typed():
    rows = client_with(200, TIDE_EXTREME_OK).tide_extremes("DT_0018", date(2026, 11, 5))
    assert [r.type for r in rows] == [TideExtremeType.LOW, TideExtremeType.HIGH]
    assert rows[0].t.isoformat() == "2026-11-05T06:34:00+09:00"
    assert rows[1].level_cm == 546.0


def test_buoy_keeps_missing_as_none_and_zero_as_zero():
    rows = client_with(200, BUOY_OK).buoy_observations("TW_0089", date(2026, 11, 5))
    assert [r.t.hour for r in rows] == [11, 12]  # 시간순 정렬
    assert rows[1].water_temp_c is None  # 결측 → None
    assert rows[0].wave_height_m == 0.0  # 실제 0 은 0 으로 유지


def test_not_registered_error_even_with_403():
    with pytest.raises(KhoaError) as e:
        client_with(403, NOT_REGISTERED).tide_hourly("DT_0018", date(2026, 11, 5))
    assert e.value.not_registered
