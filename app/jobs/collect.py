"""공공 데이터 수집 배치.

장소에 매핑된 관측소만 수집한다 (쿼터 보호). 수집 범위는 비교 조회 가능 범위와 같다.
- 조석 고·저조 / 시계열 예측: 오늘-N ~ 오늘+M 일
- 부이 실측: 오늘-N ~ 오늘 (미래 실측은 없음)
- 기상청 단기예보(파고·풍속): 최신 발표분 (약 5일)
같은 관측소·날짜는 지우고 다시 넣는다 (최신 조회 결과로 교체).
수집 후, 해당 기간에 출조한 일지의 환경정보 스냅샷을 다시 연결한다 (FR-10).

실행:
  python -m app.jobs.collect           # 1회
  python -m app.jobs.collect --loop    # 1시간마다 반복 (개발용)
"""

import argparse
import logging
import time
from collections import Counter
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clients.khoa import BuoyRow, KhoaError
from app.clients.kma import KmaForecastClient, latest_base_time
from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.core.timeutil import kst_day_range, today_kst
from app.models import Journal, OceanReading, PlaceStation, Station, TideExtreme, TideForecast
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


def _collect_tide_extremes(db, client, st: Station, day: date, stats: Counter, disabled: set) -> None:
    if "tide_extreme" in disabled:
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
    if "tide_hourly" in disabled:
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
