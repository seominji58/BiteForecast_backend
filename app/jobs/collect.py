"""공공 데이터 수집 배치.

장소에 매핑된 관측소만 수집한다 (쿼터 보호). 수집 범위는 비교 조회 가능 범위와 같다.
- 조석 고·저조 / 시계열 예측: 오늘-N ~ 오늘+M 일
- 부이 실측: 오늘-N ~ 오늘 (미래 실측은 없음)
- 기상청 단기예보(파고·풍속): 최신 발표분 (약 5일)
- 바다낚시지수: 오늘부터 약 7일 (전국 응답 중 매핑된 지점만 저장)
- 기상청 특보 현황: 매 실행 (전국 1건)
같은 관측소·날짜는 지우고 다시 넣는다 (최신 조회 결과로 교체).
수집 후, 해당 기간에 출조한 일지의 환경정보 스냅샷을 다시 연결한다 (FR-10).

실행:
  python -m app.jobs.collect           # 1회
  python -m app.jobs.collect --loop    # 1시간마다 반복 (개발용)
"""

import argparse
import json
import logging
import time
from collections import Counter
from dataclasses import asdict
from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.clients.khoa import BuoyRow, KhoaError
from app.clients.kma import KmaForecastClient, latest_base_time
from app.clients.kma_warning import KmaWarningClient
from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.core.timeutil import kst_day_range, today_kst
from app.models import (
    FishingIndex,
    Journal,
    MarineWarningSnapshot,
    OceanReading,
    PlaceStation,
    Station,
    TideExtreme,
    TideForecast,
)
from app.models.base import utcnow
from app.models.enums import DataKind, Metric, StationRole
from app.services.envlink import link_environment

log = logging.getLogger("collect")

BUOY_METRICS: list[tuple[Metric, str, str]] = [
    (Metric.WAVE_HEIGHT, "m", "wave_height_m"),
    (Metric.WIND_SPEED, "m/s", "wind_speed_ms"),
    (Metric.WATER_TEMP, "°C", "water_temp_c"),
]


def _mapped_stations(db: Session, role: StationRole) -> list[Station]:
    ids = db.scalars(select(PlaceStation.station_id).where(PlaceStation.role == role).distinct()).all()
    return list(db.scalars(select(Station).where(Station.id.in_(ids)).order_by(Station.external_id)).all())


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def collect_once(client: KmaForecastClient | None = None) -> Counter:
    s = get_settings()
    today = today_kst()
    window = _days(today - timedelta(days=s.compare_days_back), today + timedelta(days=s.compare_days_ahead))
    past = [d for d in window if d <= today]
    stats: Counter = Counter()
    own_client = client is None
    client = client or KmaForecastClient()  # 국립해양조사원 API 도 함께 호출 (KhoaClient 상속)
    disabled: set[str] = set()  # 활용신청 안 된 데이터셋은 이번 실행에서 건너뜀

    try:
        with SessionLocal() as db:
            for st in _mapped_stations(db, StationRole.TIDE):
                for day in window:
                    _collect_tide_extremes(db, client, st, day, stats, disabled)
                    _collect_tide_hourly(db, client, st, day, stats, disabled)
                db.commit()

            for st in _mapped_stations(db, StationRole.OCEAN):
                for day in past:
                    _collect_buoy(db, client, st, day, stats, disabled)
                db.commit()

            base = latest_base_time(utcnow())
            for st in _mapped_stations(db, StationRole.FORECAST):
                _collect_forecast(db, client, st, base, stats, disabled)
                db.commit()

            _collect_fishing_index(db, client, today, _mapped_stations(db, StationRole.FISHING_INDEX), stats)
            db.commit()

            _collect_warnings(db, client, stats)
            db.commit()

            # 일지 환경정보 재연결 (수집 기간에 출조한 일지)
            lo, _ = kst_day_range(window[0])
            _, hi = kst_day_range(past[-1])
            journals = db.scalars(
                select(Journal).where(
                    Journal.deleted_at.is_(None), Journal.fished_at >= lo, Journal.fished_at < hi
                )
            ).all()
            for j in journals:
                link_environment(db, j)
            stats["journals_relinked"] += len(journals)
            db.commit()
    finally:
        if own_client:
            client.close()

    for name in sorted(disabled):
        log.warning("활용신청되지 않아 건너뜀: %s", name)
    return stats


def _has_rows(db, model, st: Station, day: date) -> bool:
    lo, hi = kst_day_range(day)
    return (
        db.scalar(select(model.id).where(model.station_id == st.id, model.t >= lo, model.t < hi).limit(1))
        is not None
    )


def _collect_tide_extremes(db, client, st: Station, day: date, stats: Counter, disabled: set) -> None:
    # 조석 예측(천문조)은 다시 받아도 같으므로 이미 받은 관측소·날짜는 건너뛴다 (API 호출량 절약)
    if "tide_extreme" in disabled or _has_rows(db, TideExtreme, st, day):
        stats["tide_extreme_skipped"] += 1
        return
    try:
        rows = client.tide_extremes(st.external_id, day)
    except KhoaError as e:
        _handle_error(e, "tide_extreme", st, day, stats, disabled)
        return
    lo, hi = kst_day_range(day)
    db.execute(
        delete(TideExtreme).where(TideExtreme.station_id == st.id, TideExtreme.t >= lo, TideExtreme.t < hi)
    )
    now = utcnow()
    # 조석 예측은 발표 시각이 응답에 없으므로 issued_at 에 조회 시각을 넣는다
    db.add_all(
        TideExtreme(station_id=st.id, t=r.t, type=r.type, level_cm=r.level_cm, issued_at=now, fetched_at=now)
        for r in rows
    )
    stats["tide_extreme_rows"] += len(rows)


def _collect_tide_hourly(db, client, st: Station, day: date, stats: Counter, disabled: set) -> None:
    if "tide_hourly" in disabled or _has_rows(db, TideForecast, st, day):
        stats["tide_hourly_skipped"] += 1
        return
    try:
        rows = client.tide_hourly(st.external_id, day)
    except KhoaError as e:
        _handle_error(e, "tide_hourly", st, day, stats, disabled)
        return
    lo, hi = kst_day_range(day)
    db.execute(
        delete(TideForecast).where(
            TideForecast.station_id == st.id, TideForecast.t >= lo, TideForecast.t < hi
        )
    )
    now = utcnow()
    db.add_all(
        TideForecast(station_id=st.id, t=r.t, level_cm=r.level_cm, issued_at=now, fetched_at=now)
        for r in rows
    )
    stats["tide_hourly_rows"] += len(rows)


def _collect_buoy(db, client, st: Station, day: date, stats: Counter, disabled: set) -> None:
    if "buoy" in disabled:
        return
    lo, hi = kst_day_range(day)
    if hi <= utcnow():
        # 지난 날짜: 그 날이 끝난 뒤에 받은 적이 있으면 더 바뀌지 않음
        done = db.scalar(
            select(OceanReading.id)
            .where(
                OceanReading.station_id == st.id,
                OceanReading.kind == DataKind.OBSERVED,
                OceanReading.t >= lo,
                OceanReading.t < hi,
                OceanReading.fetched_at >= hi,
            )
            .limit(1)
        )
        if done is not None:
            stats["buoy_skipped"] += 1
            return
    try:
        rows: list[BuoyRow] = client.buoy_observations(st.external_id, day)
    except KhoaError as e:
        _handle_error(e, "buoy", st, day, stats, disabled)
        return
    lo, hi = kst_day_range(day)
    rows = [r for r in rows if lo <= r.t < hi]
    db.execute(
        delete(OceanReading).where(
            OceanReading.station_id == st.id,
            OceanReading.kind == DataKind.OBSERVED,
            OceanReading.t >= lo,
            OceanReading.t < hi,
        )
    )
    now = utcnow()
    for r in rows:
        for metric, unit, attr in BUOY_METRICS:
            db.add(
                OceanReading(
                    station_id=st.id,
                    metric=metric,
                    kind=DataKind.OBSERVED,
                    t=r.t,
                    value=getattr(r, attr),  # 결측은 None 그대로
                    unit=unit,
                    issued_at=r.t,
                    fetched_at=now,
                )
            )
    stats["buoy_rows"] += len(rows)


def _collect_forecast(
    db, client: KmaForecastClient, st: Station, base, stats: Counter, disabled: set
) -> None:
    """기상청 단기예보(파고·풍속). 격자 코드 'nx,ny'. 새 발표가 덮는 시각 이후의 예보를 교체한다"""
    if "kma_forecast" in disabled:
        return
    latest = db.scalar(
        select(func.max(OceanReading.issued_at)).where(
            OceanReading.station_id == st.id, OceanReading.kind == DataKind.FORECAST
        )
    )
    if latest is not None and latest >= base:
        stats["forecast_skipped"] += 1  # 같은 발표분은 이미 받음
        return
    nx, ny = (int(v) for v in st.external_id.split(","))
    try:
        rows = client.short_forecast(nx, ny, base)
    except KhoaError as e:
        _handle_error(e, "kma_forecast", st, base.date(), stats, disabled)
        return
    if not rows:
        return
    db.execute(
        delete(OceanReading).where(
            OceanReading.station_id == st.id,
            OceanReading.kind == DataKind.FORECAST,
            OceanReading.t >= rows[0].t,
        )
    )
    now = utcnow()
    for r in rows:
        for metric, unit, value in (
            (Metric.WAVE_HEIGHT, "m", r.wave_height_m),
            (Metric.WIND_SPEED, "m/s", r.wind_speed_ms),
        ):
            db.add(
                OceanReading(
                    station_id=st.id,
                    metric=metric,
                    kind=DataKind.FORECAST,
                    t=r.t,
                    value=value,
                    unit=unit,
                    issued_at=base,
                    fetched_at=now,
                )
            )
    stats["forecast_rows"] += len(rows)


def _collect_fishing_index(db, client, today: date, stations: list[Station], stats: Counter) -> None:
    """국립해양조사원 바다낚시지수. 한 번 호출로 전국 지점이 오므로 매핑된 지점만 골라 저장한다"""
    if not stations:
        return
    # 연결된 모든 지점에 오늘 자료가 있고 6시간 안에 받았으면 건너뜀 (새로 연결된 지점이 있으면 다시 받음)
    covered = set(
        db.scalars(
            select(FishingIndex.station_id).where(
                FishingIndex.day == today, FishingIndex.fetched_at >= utcnow() - timedelta(hours=6)
            )
        ).all()
    )
    if all(st.id in covered for st in stations):
        stats["fishing_index_skipped"] += 1
        return
    try:
        rows = client.fishing_index(today)
    except KhoaError as e:
        log.error("바다낚시지수 수집 실패: %s", e)
        stats["fishing_index_errors"] += 1
        return
    by_name = {st.external_id: st for st in stations}
    db.execute(
        delete(FishingIndex).where(
            FishingIndex.station_id.in_([st.id for st in stations]), FishingIndex.day >= today
        )
    )
    now = utcnow()
    seen: set[tuple] = set()
    for r in rows:
        st = by_name.get(r.point)
        key = (r.point, r.day, r.period, r.species)
        if st is None or key in seen:
            continue
        seen.add(key)
        db.add(
            FishingIndex(
                station_id=st.id,
                day=r.day,
                period=r.period,
                species=r.species,
                index=r.index,
                tide_phase=r.tide_phase,
                min_wave_m=r.min_wave_m,
                max_wave_m=r.max_wave_m,
                min_water_temp=r.min_water_temp,
                max_water_temp=r.max_water_temp,
                min_wind_ms=r.min_wind_ms,
                max_wind_ms=r.max_wind_ms,
                fetched_at=now,
            )
        )
    stats["fishing_index_rows"] += len(seen)


def _collect_warnings(db, client, stats: Counter) -> None:
    """기상청 특보 현황. 전국 1건이라 매 실행 받는다 (특보는 수시 발표)"""
    try:
        st = KmaWarningClient(api_key=client.api_key, http=client.http).status()
    except KhoaError as e:
        log.error("특보 현황 수집 실패: %s", e)
        stats["warning_errors"] += 1
        return
    db.add(
        MarineWarningSnapshot(
            issued_at=st.issued_at,
            fetched_at=utcnow(),
            active_json=json.dumps([asdict(w) for w in st.active], ensure_ascii=False),
            preliminary_json=json.dumps([asdict(p) for p in st.preliminary], ensure_ascii=False),
            raw_active=st.raw_active,
            raw_preliminary=st.raw_preliminary,
        )
    )
    # 오래된 스냅샷 정리 (최근 48개만 유지)
    old = db.scalars(
        select(MarineWarningSnapshot.id).order_by(MarineWarningSnapshot.fetched_at.desc()).offset(48)
    ).all()
    if old:
        db.execute(delete(MarineWarningSnapshot).where(MarineWarningSnapshot.id.in_(old)))
    stats["warning_snapshots"] += 1


def _handle_error(e: KhoaError, dataset: str, st: Station, day: date, stats: Counter, disabled: set) -> None:
    if e.not_registered:
        disabled.add(dataset)
    else:
        log.error("%s %s %s 수집 실패: %s", dataset, st.external_id, day, e)
    stats[f"{dataset}_errors"] += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="공공 해양 데이터 수집")
    parser.add_argument("--loop", action="store_true", help="1시간마다 반복 실행")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # httpx 는 INFO 에서 요청 URL 전체(serviceKey 인증키 포함)를 찍는다 → 경고 이상만 남긴다 (NFR-03)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    init_db()
    while True:
        started = time.monotonic()
        stats = collect_once()
        log.info("수집 완료 (%.0fs): %s", time.monotonic() - started, dict(stats))
        if not args.loop:
            break
        time.sleep(3600)


if __name__ == "__main__":
    main()
