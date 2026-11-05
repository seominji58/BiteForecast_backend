"""국립해양조사원 공공데이터포털 API 클라이언트 (apis.data.go.kr/1192136).

확인된 엔드포인트 (2026-11-05 실제 호출로 검증):
- 조석예보(고·저조)      tideFcstHghLw/GetTideFcstHghLwApiService   obsCode=DT_xxxx, reqDate
- 해양관측부이 최신관측   twRecent/GetTWRecentApiService            obsCode=TW_xxxx, reqDate, min
- 조석예보(시계열)        tideFcstTime/GetTideFcstTimeApiService      obsCode=DT_xxxx, reqDate, min
  → 활용신청 전이라 응답 필드 미검증. 신청 후 _parse_tide_hourly 확인 필요

공통 규칙
- 값이 없으면 None (0 으로 채우지 않음)
- 시각은 KST 로 해석해 tz-aware datetime 으로 반환
- 429(호출 과다) 는 간격을 늘려 재시도
"""

import logging
import time as _time
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from app.core.config import get_settings
from app.core.timeutil import parse_kst
from app.models.enums import TideExtremeType

log = logging.getLogger(__name__)

BASE_URL = "https://apis.data.go.kr/1192136"
AGENCY = "국립해양조사원"

EP_TIDE_EXTREME = "tideFcstHghLw/GetTideFcstHghLwApiService"
EP_TIDE_HOURLY = "tideFcstTime/GetTideFcstTimeApiService"
EP_BUOY = "twRecent/GetTWRecentApiService"

DATASET_NAMES = {
    EP_TIDE_EXTREME: "조석예보(고·저조)",
    EP_TIDE_HOURLY: "조석예보(시계열)",
    EP_BUOY: "해양관측부이 최신 관측데이터",
}


class KhoaError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

    @property
    def not_registered(self) -> bool:
        """활용신청하지 않은 API (공공데이터포털 returnReasonCode 30)"""
        return self.code in ("30", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR")


@dataclass(frozen=True)
class TideExtremeRow:
    t: datetime
    type: TideExtremeType
    level_cm: float | None


@dataclass(frozen=True)
class TideLevelRow:
    t: datetime
    level_cm: float | None


@dataclass(frozen=True)
class BuoyRow:
    t: datetime
    wave_height_m: float | None
    wind_speed_ms: float | None
    water_temp_c: float | None


def _num(v) -> float | None:
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _extreme_type(extr_se) -> TideExtremeType:
    """extrSe: 1·3 = 고조(만조), 2·4 = 저조(간조).
    실제 응답(군산 2026-11-05)에서 2=164cm, 3=546cm, 4=157cm 로 확인. 수집 시 값으로 재검증한다."""
    return TideExtremeType.HIGH if int(extr_se) % 2 == 1 else TideExtremeType.LOW


class KhoaClient:
    def __init__(self, api_key: str | None = None, http: httpx.Client | None = None):
        s = get_settings()
        self.api_key = api_key if api_key is not None else s.data_go_kr_api_key
        if not self.api_key:
            raise KhoaError("NO_KEY", "DATA_GO_KR_API_KEY 가 설정되지 않았습니다")
        self.http = http or httpx.Client(timeout=s.external_timeout_seconds)
        self.retries = s.external_retries
        self.min_interval = s.external_min_interval_seconds
        self._last_call = 0.0

    def close(self) -> None:
        self.http.close()

    def _get(self, endpoint: str, params: dict) -> list[dict]:
        q = {"serviceKey": self.api_key, "type": "json", "pageNo": 1, "numOfRows": 300, **params}
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (_time.monotonic() - self._last_call)
            if wait > 0:
                _time.sleep(wait)
            self._last_call = _time.monotonic()
            try:
                res = self.http.get(f"{BASE_URL}/{endpoint}", params=q)
            except httpx.HTTPError as e:
                if attempt < self.retries:
                    _time.sleep(1 + attempt)
                    continue
                raise KhoaError("NETWORK", repr(e)) from e

            if res.status_code == 429 and attempt < self.retries:
                _time.sleep(3 * (attempt + 1))
                continue
            return self._parse(res)
        raise KhoaError("429", "호출 한도 초과")

    @staticmethod
    def _parse(res: httpx.Response) -> list[dict]:
        # 포털은 오류도 403 등과 함께 JSON 본문으로 보내므로 본문을 먼저 해석한다
        try:
            data = res.json()
        except ValueError:
            raise KhoaError(
                str(res.status_code) if res.status_code != 200 else "NOT_JSON", res.text[:200]
            ) from None

        # 포털 공통 오류 형식
        err = data.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader") if isinstance(data, dict) else None
        if err:
            raise KhoaError(
                str(err.get("returnReasonCode")), err.get("returnAuthMsg") or err.get("errMsg", "")
            )
        if res.status_code != 200:
            raise KhoaError(str(res.status_code), res.text[:200])

        header = data.get("header", {})
        if header.get("resultCode") not in ("00", None):
            raise KhoaError(str(header.get("resultCode")), header.get("resultMsg", ""))

        items = (data.get("body") or {}).get("items") or {}
        item = items.get("item") if isinstance(items, dict) else items
        if item is None:
            return []
        return item if isinstance(item, list) else [item]

    # --- 조석 ---

    def tide_extremes(self, obs_code: str, day: date) -> list[TideExtremeRow]:
        items = self._get(EP_TIDE_EXTREME, {"obsCode": obs_code, "reqDate": day.strftime("%Y%m%d")})
        rows = [
            TideExtremeRow(
                t=parse_kst(i["predcDt"]),
                type=_extreme_type(i["extrSe"]),
                level_cm=_num(i.get("predcTdlvVl")),
            )
            for i in items
            if i.get("predcDt") and i.get("extrSe")
        ]
        _check_extremes(obs_code, day, rows)
        return sorted(rows, key=lambda r: r.t)

    def tide_hourly(self, obs_code: str, day: date) -> list[TideLevelRow]:
        items = self._get(EP_TIDE_HOURLY, {"obsCode": obs_code, "reqDate": day.strftime("%Y%m%d"), "min": 60})
        return _parse_tide_hourly(items)

    # --- 부이 ---

    def buoy_observations(self, obs_code: str, day: date) -> list[BuoyRow]:
        items = self._get(EP_BUOY, {"obsCode": obs_code, "reqDate": day.strftime("%Y%m%d"), "min": 60})
        rows = [
            BuoyRow(
                t=parse_kst(i["obsrvnDt"]),
                wave_height_m=_num(i.get("wvhgt")),
                wind_speed_ms=_num(i.get("wspd")),
                water_temp_c=_num(i.get("wtem")),
            )
            for i in items
            if i.get("obsrvnDt")
        ]
        return sorted(rows, key=lambda r: r.t)


def _parse_tide_hourly(items: list[dict]) -> list[TideLevelRow]:
    """필드명 미검증: 고·저조 API 와 같은 predcDt / predcTdlvVl 을 우선 가정하고 후보를 순서대로 찾는다"""
    rows = []
    for i in items:
        ts = i.get("predcDt") or i.get("obsrvnDt")
        if not ts:
            continue
        val = next((i[k] for k in ("predcTdlvVl", "tdlvHgt", "bscTdlvHgt", "tideLevel") if k in i), None)
        rows.append(TideLevelRow(t=parse_kst(ts), level_cm=_num(val)))
    if items and not rows:
        log.warning("조석예보(시계열) 응답 필드를 해석하지 못했습니다: %s", list(items[0].keys()))
    return sorted(rows, key=lambda r: r.t)


def _check_extremes(obs_code: str, day: date, rows: list[TideExtremeRow]) -> None:
    """extrSe 해석 검증: 고조 값이 저조 값보다 커야 한다"""
    highs = [r.level_cm for r in rows if r.type == TideExtremeType.HIGH and r.level_cm is not None]
    lows = [r.level_cm for r in rows if r.type == TideExtremeType.LOW and r.level_cm is not None]
    if highs and lows and min(highs) <= max(lows):
        log.warning("고·저조 구분이 값과 맞지 않습니다 (%s %s): high=%s low=%s", obs_code, day, highs, lows)
