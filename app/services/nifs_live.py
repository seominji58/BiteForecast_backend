"""국립수산과학원 실시간 자료 (2026-11-24): 실시간 연안 수온(RISA)·적조 속보·해파리 주간보고.

DB 에 저장하지 않고 API 서버 메모리에 30분 보관한다 (해상 특보 갱신과 같은 방식, 마이그레이션 없음).
- 오래됐으면 뒤에서 한 번 받는다 (요청은 기다리지 않음, 첫 요청만 최대 3초 기다림)
- 운영 환경 + 키가 있을 때만 외부 호출 (테스트·로컬은 비어 있음)
- RISA 는 품질처리 전 자료라 「참고」로만 쓰고, 점검 중(rpr_yn=Y)·관측 3시간 넘은 값은 버린다
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

from app.core.config import get_settings
from app.core.geo import haversine_km

log = logging.getLogger("nifs_live")

BASE = "https://www.nifs.go.kr/api/OpenAPI_json"
KST = timezone(timedelta(hours=9))
REFRESH_SECONDS = 30 * 60
RETRY_AFTER_FAIL_SECONDS = 5 * 60
MAX_AGE = timedelta(hours=3)
NEAR_KM = 20.0
SEA_NAME = {"동해": "동해", "서해": "서해", "남해": "남해"}


@dataclass
class RisaStation:
    code: str
    name: str
    sea: str
    lat: float
    lon: float
    temp: float | None = None
    at: datetime | None = None


@dataclass
class Live:
    stations: list[RisaStation] = field(default_factory=list)
    redtide: list[dict] = field(default_factory=list)
    jelly: list[dict] = field(default_factory=list)
    fetched: float = 0.0


_live = Live()
_lock = threading.Lock()
_running = False
_last_fail = 0.0
_done = threading.Event()
_done.set()


def _enabled() -> bool:
    s = get_settings()
    return s.app_env == "prod" and bool(s.nifs_risa_key or s.nifs_redtide_key or s.nifs_jelly_key)


def _get(http: httpx.Client, key: str, **params) -> list[dict]:
    r = http.get(BASE, params={"key": key, **params}, follow_redirects=True)
    r.raise_for_status()
    d = r.json()
    if (d.get("header") or {}).get("resultCode") != "00":
        raise RuntimeError(f"{params.get('id')}: {(d.get('header') or {}).get('resultMsg')}")
    item = (d.get("body") or {}).get("item") or []
    return item if isinstance(item, list) else [item]


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_risa(codes: list[dict], obs: list[dict]) -> list[RisaStation]:
    """관측소(위치) + 최신 관측(표층만, 점검 중 제외)을 합친다"""
    stations: dict[str, RisaStation] = {}
    for c in codes:
        lat, lon = _num(c.get("lat")), _num(c.get("lon"))
        if lat is None or lon is None or c.get("sur_tmp_yn") == "N":
            continue
        stations[c["sta_cde"]] = RisaStation(
            c["sta_cde"], c.get("sta_nam_kor", ""), c.get("gru_nam", ""), lat, lon
        )
    for o in obs:
        st = stations.get(o.get("sta_cde"))
        v = _num(o.get("wtr_tmp"))
        if st is None or o.get("obs_lay") != "1" or o.get("rpr_yn") == "Y" or v is None or not -2 <= v <= 35:
            continue
        try:
            at = datetime.strptime(f"{o['obs_dat']} {o['obs_tim']}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        except (KeyError, ValueError):
            continue
        if st.at is None or at > st.at:
            st.temp, st.at = v, at
    return list(stations.values())


def _fetch() -> None:
    global _live
    s = get_settings()
    today = datetime.now(KST).date()
    new = Live(fetched=time.monotonic())
    with httpx.Client(timeout=10) as http:
        if s.nifs_risa_key:
            new.stations = parse_risa(
                _get(http, s.nifs_risa_key, id="risaCode", use_yn="Y"),
                _get(http, s.nifs_risa_key, id="risaList"),
            )
        if s.nifs_redtide_key:
            start = (today - timedelta(days=21)).strftime("%Y%m%d")
            new.redtide = _get(
                http, s.nifs_redtide_key, id="redtideList", sdate=start, edate=today.strftime("%Y%m%d")
            )
            for r in sorted(new.redtide, key=lambda x: x.get("day_report", ""), reverse=True)[:3]:
                try:
                    d = _get(http, s.nifs_redtide_key, id="redtideDetail", cod_news=r["cod_news"])
                    r.update(d[0] if d else {})
                except (httpx.HTTPError, RuntimeError, KeyError):
                    pass
        if s.nifs_jelly_key:
            start = (today - timedelta(days=30)).strftime("%Y%m%d")
            new.jelly = _get(
                http, s.nifs_jelly_key, id="jellyList", sdate=start, edate=today.strftime("%Y%m%d")
            )
    with _lock:
        _live = new


def _run() -> None:
    global _running, _last_fail
    try:
        _fetch()
    except Exception as e:  # noqa: BLE001 — 외부 자료 실패가 화면을 막지 않게
        _last_fail = time.monotonic()
        log.warning("수산과학원 자료 받기 실패: %s", e)
    finally:
        with _lock:
            _running = False
        _done.set()


def live(wait: float = 3.0) -> Live:
    """지금 보관 중인 자료. 오래됐으면 뒤에서 받는다 (처음이면 최대 wait 초 기다림)"""
    global _running
    if not _enabled():
        return _live
    now = time.monotonic()
    with _lock:
        stale = now - _live.fetched > REFRESH_SECONDS
        start = stale and not _running and now - _last_fail > RETRY_AFTER_FAIL_SECONDS
        if start:
            _running = True
            _done.clear()
    if start:
        threading.Thread(target=_run, name="nifs-live", daemon=True).start()
    if _live.fetched == 0 and wait:
        _done.wait(wait)
    return _live


def nearest_temp(
    stations: list[RisaStation], lat: float | None, lon: float | None, sea: str | None, now: datetime
):
    """같은 바다 NEAR_KM 안 가장 가까운 관측소의 최신 표층 수온 (3시간 넘은 값은 버림)"""
    if lat is None or lon is None:
        return None
    best = None
    for st in stations:
        if st.temp is None or st.at is None or now - st.at > MAX_AGE:
            continue
        if sea and st.sea and st.sea != sea and not (sea == "제주" and st.sea == "남해"):
            continue
        d = haversine_km(lat, lon, st.lat, st.lon)
        if d <= NEAR_KM and (best is None or d < best[0]):
            best = (d, st)
    return best


def recent_redtide(items: list[dict], today: date, days: int = 14) -> list[dict]:
    """최근 days 일 안의 적조 속보 (최신순)"""
    out = []
    for r in items:
        try:
            d = datetime.strptime(str(r.get("day_report", ""))[:8], "%Y%m%d").date()
        except ValueError:
            continue
        if (today - d).days <= days:
            out.append({**r, "_date": d})
    return sorted(out, key=lambda x: x["_date"], reverse=True)
