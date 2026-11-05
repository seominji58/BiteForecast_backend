"""A/B 환경 비교 (FR-02~05, FR-07).

- DB 에 수집된 자료만 사용한다 (요청 시 외부 API 호출 없음, NFR-06)
- 예보와 실측은 서로 다른 계열로 분리한다 (TC-03)
- 값이 없으면 null, 계열 자체가 없으면 status=unavailable + reason (TC-02)
- 보간하지 않는다. 원본 시각 그대로 내보낸다
"""

from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.clients.khoa import AGENCY, DATASET_NAMES, EP_BUOY, EP_TIDE_EXTREME, EP_TIDE_HOURLY
from app.clients.kma import AGENCY as KMA_AGENCY
from app.clients.kma import DATASET as KMA_DATASET
from app.core.config import get_settings
from app.core.timeutil import kst_day_range, today_kst
from app.models import OceanReading, Place, PlaceStation, TideExtreme, TideForecast
from app.models.base import utcnow
from app.models.enums import DataKind, Metric, StationRole
from app.schemas.compare import (
    CompareOut,
    DateRangeOut,
    ExtremeOut,
    PlaceCompareOut,
    PointOut,
    SeriesOut,
    SourceOut,
)
from app.schemas.place import PlaceOut
from app.services.regulation import evaluate

DISCLAIMER = (
    "실제 입질·조과를 보장하지 않으며, 관측소 값은 낚시 장소의 현장 조건과 다를 수 있습니다. "
    "출조 전 공식 특보와 현장 출입 제한을 확인하세요."
)

OCEAN_METRICS: list[tuple[Metric, str]] = [
    (Metric.WAVE_HEIGHT, "m"),
    (Metric.WIND_SPEED, "m/s"),
    (Metric.WATER_TEMP, "°C"),
]
# 기상청 단기예보로 예보를 제공하는 지표
FORECAST_METRICS = {Metric.WAVE_HEIGHT, Metric.WIND_SPEED}


def date_range() -> DateRangeOut:
    s = get_settings()
    today = today_kst()
    return DateRangeOut(
        today=today,
        min=today - timedelta(days=s.compare_days_back),
        max=today + timedelta(days=s.compare_days_ahead),
    )


def compare(db: Session, place_a: int, place_b: int, day: date) -> CompareOut:
    if place_a == place_b:
        raise HTTPException(status_code=400, detail="서로 다른 두 장소를 선택해 주세요")
    rng = date_range()
    if not (rng.min <= day <= rng.max):
        raise HTTPException(status_code=400, detail=f"조회 가능한 날짜는 {rng.min} ~ {rng.max} 입니다")

    places = []
    for pid in (place_a, place_b):
        p = db.scalar(
            select(Place)
            .where(Place.id == pid, Place.is_active.is_(True))
            .options(
                selectinload(Place.region), selectinload(Place.stations).selectinload(PlaceStation.station)
            )
        )
        if p is None:
            raise HTTPException(status_code=400, detail="지원하지 않는 장소입니다")
        places.append(p)

    return CompareOut(
        date=day,
        generated_at=utcnow(),
        places=[_place_compare(db, p, day) for p in places],
        disclaimer=DISCLAIMER,
    )


def _source(ps: PlaceStation, endpoint: str) -> SourceOut:
    return SourceOut(
        agency=AGENCY,
        dataset=DATASET_NAMES[endpoint],
        station_code=ps.station.external_id,
        station_name=ps.station.name,
        distance_km=ps.distance_km,
    )


def _forecast_series(db: Session, ps: PlaceStation | None, metric: Metric, unit: str, lo, hi) -> SeriesOut:
    if ps is None:
        return _unavailable(metric.value, unit, DataKind.FORECAST, "NO_STATION")
    source = SourceOut(
        agency=KMA_AGENCY,
        dataset=KMA_DATASET,
        station_code=ps.station.external_id,
        station_name=ps.station.name,
        distance_km=ps.distance_km,
    )
    rows = db.scalars(
        select(OceanReading)
        .where(
            OceanReading.station_id == ps.station_id,
            OceanReading.metric == metric,
            OceanReading.kind == DataKind.FORECAST,
            OceanReading.t >= lo,
            OceanReading.t < hi,
        )
        .order_by(OceanReading.t)
    ).all()
    if not rows:
        # 단기예보는 약 5일치만 제공 → 그 이후 날짜는 자료 없음
        return _unavailable(metric.value, unit, DataKind.FORECAST, "NO_DATA", source)
    return SeriesOut(
        metric=metric.value,
        unit=unit,
        kind=DataKind.FORECAST,
        status="ok",
        source=source,
        issued_at=max(r.issued_at for r in rows),
        fetched_at=max(r.fetched_at for r in rows),
        points=[PointOut(t=r.t, v=r.value) for r in rows],
    )


def _place_compare(db: Session, place: Place, day: date) -> PlaceCompareOut:
    by_role = {ps.role: ps for ps in place.stations}
    lo, hi = kst_day_range(day)
    now = utcnow()
    series: list[SeriesOut] = []

    # --- 조석: 고·저조 (예보) ---
    tide = by_role.get(StationRole.TIDE)
    if tide is None:
        series.append(_unavailable("tide_extreme", "cm", DataKind.FORECAST, "NO_STATION"))
        series.append(_unavailable("tide_level", "cm", DataKind.FORECAST, "NO_STATION"))
    else:
        ext = db.scalars(
            select(TideExtreme)
            .where(TideExtreme.station_id == tide.station_id, TideExtreme.t >= lo, TideExtreme.t < hi)
            .order_by(TideExtreme.t)
        ).all()
        series.append(
            SeriesOut(
                metric="tide_extreme",
                unit="cm",
                kind=DataKind.FORECAST,
                status="ok" if ext else "unavailable",
                reason=None if ext else "NO_DATA",
                source=_source(tide, EP_TIDE_EXTREME),
                issued_at=max((e.issued_at for e in ext), default=None),
                fetched_at=max((e.fetched_at for e in ext), default=None),
                extremes=[ExtremeOut(t=e.t, type=e.type, v=e.level_cm) for e in ext] if ext else None,
            )
        )

        lv = db.scalars(
            select(TideForecast)
            .where(TideForecast.station_id == tide.station_id, TideForecast.t >= lo, TideForecast.t < hi)
            .order_by(TideForecast.t)
        ).all()
        series.append(
            SeriesOut(
                metric="tide_level",
                unit="cm",
                kind=DataKind.FORECAST,
                status="ok" if lv else "unavailable",
                reason=None if lv else "NO_DATA",
                source=_source(tide, EP_TIDE_HOURLY),
                issued_at=max((r.issued_at for r in lv), default=None),
                fetched_at=max((r.fetched_at for r in lv), default=None),
                points=[PointOut(t=r.t, v=r.level_cm) for r in lv] if lv else None,
            )
        )

    # --- 파고·풍속·수온 ---
    ocean = by_role.get(StationRole.OCEAN)
    for metric, unit in OCEAN_METRICS:
        # 실측: 미래 날짜에는 없다. 실측을 예보처럼 보여주지 않는다 (FR-04)
        if ocean is None:
            series.append(_unavailable(metric.value, unit, DataKind.OBSERVED, "NO_STATION"))
        elif lo > now:
            series.append(
                _unavailable(metric.value, unit, DataKind.OBSERVED, "FUTURE_DATE", _source(ocean, EP_BUOY))
            )
        else:
            rows = db.scalars(
                select(OceanReading)
                .where(
                    OceanReading.station_id == ocean.station_id,
                    OceanReading.metric == metric,
                    OceanReading.kind == DataKind.OBSERVED,
                    OceanReading.t >= lo,
                    OceanReading.t < min(hi, now),
                )
                .order_by(OceanReading.t)
            ).all()
            series.append(
                SeriesOut(
                    metric=metric.value,
                    unit=unit,
                    kind=DataKind.OBSERVED,
                    status="ok" if rows else "unavailable",
                    reason=None if rows else "NO_DATA",
                    source=_source(ocean, EP_BUOY),
                    issued_at=rows[-1].t if rows else None,
                    fetched_at=max((r.fetched_at for r in rows), default=None),
                    points=[PointOut(t=r.t, v=r.value) for r in rows] if rows else None,
                )
            )

        # 예보: 기상청 단기예보 격자 (실측 부이와 같은 위치). 실측과 별도 계열로 내보낸다 (TC-03)
        if metric in FORECAST_METRICS:
            series.append(_forecast_series(db, by_role.get(StationRole.FORECAST), metric, unit, lo, hi))

    return PlaceCompareOut(
        place=PlaceOut.model_validate(place),
        region_name=place.region.name,
        regulation=evaluate(db, place.id, day),
        series=series,
    )


def _unavailable(
    metric: str, unit: str, kind: DataKind, reason: str, source: SourceOut | None = None
) -> SeriesOut:
    return SeriesOut(metric=metric, unit=unit, kind=kind, status="unavailable", reason=reason, source=source)
