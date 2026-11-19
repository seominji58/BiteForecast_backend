"""물때(몇 물)·일출·일몰 계산 — 외부 API·라이브러리 없이 천문 계산식으로 (2026-11-17).

물때
- 음력 날짜만 알면 정해진다. 음력 1일 = 한국 시간으로 합삭(新月)이 든 날
- 합삭 시각: Meeus, Astronomical Algorithms 49장 (오차 수 분)
- 서해 7물때식 / 남해·동해·제주 8물때식 (바다타임 물때 안내, 한국항해학회지 「우리나라의 물때체계」)
  · 7물때식: 음력 1·16일 7물 → … → 7·22일 13물, 8·23일 조금, 9·24일 무시, 10·25일 1물 … 15·30일 6물
  · 8물때식: 음력 1·16일 8물 → … → 7·22일 14물, 8·23일 조금, 9·24일 1물 … 15·30일 7물
- 조석 「예보」가 아니라 달력 계산이다. 실제 만조·간조 시각은 조위관측소 예보를 본다

일출·일몰: NOAA 태양 위치 계산식 (대기 굴절 포함 −0.833°, 오차 1~2분)
"""

import math
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
_SYNODIC = 29.530588861


def _jde_to_datetime(jde: float) -> datetime:
    # 역학시(TT) ≈ UTC + 69초 (2020년대). 날짜 경계 판단에는 영향이 거의 없다
    unix = (jde - 2440587.5) * 86400.0 - 69.0
    return datetime.fromtimestamp(unix, tz=timezone.utc)


def _new_moon_jde(k: int) -> float:
    """k 번째 합삭 (k=0 이 2000-01-06 무렵). Meeus 49장"""
    t = k / 1236.85
    jde = 2451550.09766 + 29.530588861 * k + 0.00015437 * t**2 - 0.000000150 * t**3 + 0.00000000073 * t**4
    e = 1 - 0.002516 * t - 0.0000074 * t**2
    m = math.radians((2.5534 + 29.10535670 * k - 0.0000014 * t**2 - 0.00000011 * t**3) % 360)
    mp = math.radians(
        (201.5643 + 385.81693528 * k + 0.0107582 * t**2 + 0.00001238 * t**3 - 0.000000058 * t**4) % 360
    )
    f = math.radians(
        (160.7108 + 390.67050284 * k - 0.0016118 * t**2 - 0.00000227 * t**3 + 0.000000011 * t**4) % 360
    )
    om = math.radians((124.7746 - 1.56375588 * k + 0.0020672 * t**2 + 0.00000215 * t**3) % 360)
    corr = (
        -0.40720 * math.sin(mp)
        + 0.17241 * e * math.sin(m)
        + 0.01608 * math.sin(2 * mp)
        + 0.01039 * math.sin(2 * f)
        + 0.00739 * e * math.sin(mp - m)
        - 0.00514 * e * math.sin(mp + m)
        + 0.00208 * e * e * math.sin(2 * m)
        - 0.00111 * math.sin(mp - 2 * f)
        - 0.00057 * math.sin(mp + 2 * f)
        + 0.00056 * e * math.sin(2 * mp + m)
        - 0.00042 * math.sin(3 * mp)
        + 0.00042 * e * math.sin(m + 2 * f)
        + 0.00038 * e * math.sin(m - 2 * f)
        - 0.00024 * e * math.sin(2 * mp - m)
        - 0.00017 * math.sin(om)
        - 0.00007 * math.sin(mp + 2 * m)
        + 0.00004 * math.sin(2 * mp - 2 * f)
        + 0.00004 * math.sin(3 * m)
        + 0.00003 * math.sin(mp + m - 2 * f)
        + 0.00003 * math.sin(2 * mp + 2 * f)
        - 0.00003 * math.sin(mp + m + 2 * f)
        + 0.00003 * math.sin(mp - m + 2 * f)
        - 0.00002 * math.sin(mp - m - 2 * f)
        - 0.00002 * math.sin(3 * mp + m)
        + 0.00002 * math.sin(4 * mp)
    )
    # 행성 보정 (A1~A14)
    a = [
        299.77 + 0.107408 * k - 0.009173 * t**2,
        251.88 + 0.016321 * k,
        251.83 + 26.651886 * k,
        349.42 + 36.412478 * k,
        84.66 + 18.206239 * k,
        141.74 + 53.303771 * k,
        207.14 + 2.453732 * k,
        154.84 + 7.306860 * k,
        34.52 + 27.261239 * k,
        207.19 + 0.121824 * k,
        291.34 + 1.844379 * k,
        161.72 + 24.198154 * k,
        239.56 + 25.513099 * k,
        331.55 + 3.592518 * k,
    ]
    coef = [
        0.000325,
        0.000165,
        0.000164,
        0.000126,
        0.000110,
        0.000062,
        0.000060,
        0.000056,
        0.000047,
        0.000042,
        0.000040,
        0.000037,
        0.000035,
        0.000023,
    ]
    corr += sum(c * math.sin(math.radians(x % 360)) for c, x in zip(coef, a, strict=True))
    return jde + corr


def lunar_day(day: date) -> int:
    """음력 날짜(1~30): 한국 시간으로 그날 이전(그날 포함) 마지막 합삭이 든 날이 1일"""
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=KST)
    k = math.floor(
        (noon - datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)).total_seconds() / 86400 / _SYNODIC
    )
    for kk in (k + 1, k, k - 1, k - 2):
        nm = _jde_to_datetime(_new_moon_jde(kk)).astimezone(KST).date()
        if nm <= day:
            return (day - nm).days + 1
    raise ValueError("합삭을 찾지 못했어요")


def mulddae_name(lday: int, west: bool) -> str:
    """음력 날짜 → 물때 이름. west=True 면 서해 7물때식, 아니면 8물때식(남해·동해·제주)"""
    i = (lday - 1) % 15  # 1·16일 = 0
    if i == 7:
        return "조금"
    if west:
        return f"{i + 7}물" if i < 7 else "무시" if i == 8 else f"{i - 8}물"
    return f"{i + 8}물" if i < 7 else f"{i - 7}물"


def mulddae(day: date, west: bool) -> str:
    """물때 이름 (음력은 합삭 계산)"""
    return mulddae_name(lunar_day(day), west)


def sun_times(lat: float, lon: float, day: date) -> tuple[str | None, str | None]:
    """일출·일몰 (KST HH:MM). 극야·백야면 None"""

    def calc(rise: bool) -> str | None:
        n = day.timetuple().tm_yday
        lng_hour = lon / 15
        t = n + ((6 if rise else 18) - lng_hour) / 24
        m = 0.9856 * t - 3.289
        l = (m + 1.916 * math.sin(math.radians(m)) + 0.020 * math.sin(math.radians(2 * m)) + 282.634) % 360  # noqa: E741
        ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l)))) % 360
        ra = (ra + (math.floor(l / 90) * 90 - math.floor(ra / 90) * 90)) / 15
        sin_dec = 0.39782 * math.sin(math.radians(l))
        cos_dec = math.cos(math.asin(sin_dec))
        cos_h = (math.cos(math.radians(90.833)) - sin_dec * math.sin(math.radians(lat))) / (
            cos_dec * math.cos(math.radians(lat))
        )
        if not -1 <= cos_h <= 1:
            return None
        h = (360 - math.degrees(math.acos(cos_h)) if rise else math.degrees(math.acos(cos_h))) / 15
        local_t = h + ra - 0.06571 * t - 6.622
        ut = (local_t - lng_hour) % 24
        kst = (ut + 9) % 24
        hh, mm = int(kst), int(round((kst - int(kst)) * 60))
        if mm == 60:
            hh, mm = (hh + 1) % 24, 0
        return f"{hh:02d}:{mm:02d}"

    return calc(True), calc(False)


# ── 한국천문연구원 공식 자료 (2026-11-19) ─────────────────────────────────────
# 일출·일몰: 출몰시각 정보(RiseSetInfoService)
#   좌표 0.1° 격자(약 10km, 일출 차이 1분 미만)·날짜별로 한 번 받아 둔다
# 음력 날짜: 음양력 정보(LrsrCldInfoService) — 날짜별 한 번. 물때 규칙(7·8물때식)은 그대로
# 받지 못하면(키 미승인·장애) 위의 계산식으로 대신하고, 어느 쪽인지 출처로 알린다
KASI = "한국천문연구원"
CALC = "계산"
_KASI_BASE = "http://apis.data.go.kr/B090041/openapi/service"
_sun_cache: dict[tuple[float, float, date], tuple[str | None, str | None]] = {}
# 받지 못한 좌표·날짜 → 그 시각 (장애 때 같은 곳을 계속 다시 부르지 않게 10분 쉼)
_sun_fail: dict[tuple[float, float, date], float] = {}
_RETRY_SECONDS = 600
_lunar_cache: dict[date, int | None] = {}


_client = None
_client_lock = __import__("threading").Lock()


def _http():
    """KASI 호출용 클라이언트 하나를 같이 쓴다 (호출마다 새로 만들면 작은 서버에서 CPU·메모리를 먹는다)"""
    global _client
    with _client_lock:
        if _client is None:
            import httpx

            _client = httpx.Client(
                timeout=5, limits=httpx.Limits(max_connections=4, max_keepalive_connections=4)
            )
        return _client


def _kasi_item(path: str, params: dict) -> dict | None:
    from app.core.config import get_settings

    s = get_settings()
    if s.app_env == "test" or not s.data_go_kr_api_key:
        return None
    try:
        r = _http().get(
            f"{_KASI_BASE}/{path}",
            params={"serviceKey": s.data_go_kr_api_key, "_type": "json", **params},
        )
        r.raise_for_status()
        item = r.json()["response"]["body"]["items"]["item"]
        return item[0] if isinstance(item, list) else item
    except Exception:  # noqa: BLE001 — 외부 자료가 안 오면 계산식으로
        return None


def _hhmm(v) -> str | None:
    v = str(v or "").strip()
    return f"{v[:2]}:{v[2:4]}" if len(v) >= 4 and v[:4].isdigit() else None


def _cell(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, 1), round(lon, 1)


def _fetch_sun(lat: float, lon: float, day: date) -> tuple[str | None, str | None] | None:
    item = _kasi_item(
        "RiseSetInfoService/getLCRiseSetInfo",
        {"longitude": lon, "latitude": lat, "locdate": day.strftime("%Y%m%d"), "dnYn": "Y"},
    )
    if not item:
        return None
    rise, sset = _hhmm(item.get("sunrise")), _hhmm(item.get("sunset"))
    return (rise, sset) if rise and sset else None


def prefetch_sun(points: list[tuple[float, float]], day: date, workers: int = 4) -> int:
    """여러 낚시터 좌표의 공식 일출·일몰을 한꺼번에 받아 둔다 (없는 것만, 동시에). 새로 받은 개수"""
    import time
    from concurrent.futures import ThreadPoolExecutor

    # 지난 날짜만 지운다 (미래 날짜를 받을 때 오늘 것을 지우지 않게 — 기준은 요청 날짜가 아니라 오늘)
    today = datetime.now(KST).date()
    for k in [k for k in _sun_cache if k[2] < today - timedelta(days=1)]:
        _sun_cache.pop(k, None)
    now = time.monotonic()
    keys = {(*_cell(a, b), day) for a, b in points}
    todo = sorted(k for k in keys if k not in _sun_cache and now - _sun_fail.get(k, -1e9) > _RETRY_SECONDS)
    if not todo:
        return 0
    got = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, v in zip(todo, ex.map(lambda k: _fetch_sun(k[0], k[1], day), todo), strict=True):
            if v:
                _sun_cache[k] = v
                _sun_fail.pop(k, None)
                got += 1
            else:
                _sun_fail[k] = now
    return got


_bg_lock = __import__("threading").Lock()
_bg_queue: dict[date, tuple[list[tuple[float, float]], object]] = {}
_bg_thread = None


def prefetch_sun_background(points: list[tuple[float, float]], day: date, on_done) -> None:
    """전체 요약용: 응답을 기다리게 하지 않고 뒤에서 받는다. 새로 받은 게 있으면 on_done() (요약 캐시 비우기)
    작은 서버를 지키려고 뒤에서 받는 일꾼은 하나뿐이고, 날짜는 차례로 처리한다 (2026-11-19 서버 멈춤 수정)"""
    import threading

    global _bg_thread
    with _bg_lock:
        _bg_queue.setdefault(day, (points, on_done))
        if _bg_thread is not None and _bg_thread.is_alive():
            return

        def run():
            while True:
                global _bg_thread
                with _bg_lock:
                    if not _bg_queue:
                        _bg_thread = None  # 끝나기 직전에 들어온 날짜는 새 일꾼이 맡는다
                        return
                    d, (pts, done) = next(iter(_bg_queue.items()))
                try:
                    if prefetch_sun(pts, d):
                        done()
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    with _bg_lock:
                        _bg_queue.pop(d, None)

        _bg_thread = threading.Thread(target=run, daemon=True)
        _bg_thread.start()


def official_sun_times(
    lat: float, lon: float, day: date, fetch: bool = False
) -> tuple[str | None, str | None, str]:
    """(일출, 일몰, 출처). fetch=True 면 없을 때 한 곳만 바로 받아 본다 (출조 계획 등 낱개 조회)"""
    if fetch:
        prefetch_sun([(lat, lon)], day)
    c = _cell(lat, lon)
    hit = _sun_cache.get((c[0], c[1], day))
    if hit:
        return hit[0], hit[1], KASI
    rise, sset = sun_times(lat, lon, day)
    return rise, sset, CALC


def official_lunar_day(day: date) -> tuple[int, str]:
    """(음력 날짜, 출처). 공식 음양력 자료가 없으면 합삭 계산"""
    if day not in _lunar_cache:
        item = _kasi_item(
            "LrsrCldInfoService/getLunCalInfo",
            {"solYear": day.year, "solMonth": f"{day.month:02d}", "solDay": f"{day.day:02d}"},
        )
        try:
            _lunar_cache[day] = int(item["lunDay"]) if item else None
        except (KeyError, TypeError, ValueError):
            _lunar_cache[day] = None
    v = _lunar_cache[day]
    return (v, KASI) if v else (lunar_day(day), CALC)


def mulddae_official(day: date, west: bool) -> tuple[str, str]:
    """(물때, 음력 출처). 물때 규칙은 같고, 음력 날짜만 공식 자료를 쓴다"""
    lday, src = official_lunar_day(day)
    return mulddae_name(lday, west), src
