"""A/B 환경 비교 (FR-02~05, FR-07).

- DB 에 수집된 자료만 사용한다 (요청 시 외부 API 호출 없음, NFR-06)
- 예보와 실측은 서로 다른 계열로 분리한다 (TC-03)
- 값이 없으면 null, 계열 자체가 없으면 status=unavailable + reason (TC-02)
- 보간하지 않는다. 원본 시각 그대로 내보낸다
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.clients.khoa import (
    AGENCY,
    DATASET_NAMES,
    EP_BUOY,
    EP_FISHING_INDEX,
    EP_TIDE_EXTREME,
    EP_TIDE_HOURLY,
)
from app.clients.kma import AGENCY as KMA_AGENCY
from app.clients.kma import DATASET as KMA_DATASET
from app.core.config import get_settings
from app.core.timeutil import kst_day_range, today_kst
from app.models import (
    FishingIndex,
    MarineWarningSnapshot,
    OceanReading,
    Place,
    PlaceStation,
    TideExtreme,
    TideForecast,
)
from app.models.base import utcnow
from app.models.enums import DataKind, Metric, StationRole
from app.schemas.compare import (
    CompareOut,
    DateRangeOut,
    ExtremeOut,
    FishingIndexOut,
    FishingPeriodOut,
    FishingSpeciesOut,
    PlaceCompareOut,
    PlaceConditionsOut,
    PointOut,
    SeriesOut,
    SourceOut,
    WarningOut,
)
from app.services import regulation
from app.services.location import LocationCtx, location_ctx, place_out, same_sea
from app.services.regulation import evaluate
from app.services.warning import collection_health, latest_snapshot
from app.services.warning import evaluate as evaluate_warning

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
WEATHER_FORECAST_METRICS: list[tuple[Metric, str]] = [
    (Metric.AIR_TEMP, "°C"),
    (Metric.PRECIPITATION_PROBABILITY, "%"),
    (Metric.SKY_STATE, "code"),
    (Metric.PRECIPITATION_TYPE, "code"),
]


@dataclass
class Prefetch:
    """한 요청에서 여러 낚시터의 하루 자료를 표마다 한 번씩만 읽어 둔 묶음.

    원격 DB(Supabase)는 왕복마다 수 ms~수십 ms 가 들어, 장소마다 조회하면 전체 요약이 수천 번 왕복한다.
    계산 규칙은 그대로이고 읽는 방법만 다르다 (장소 1곳 조회도 같은 경로)."""

    day: date
    lo: datetime
    hi: datetime
    now: datetime
    loc: LocationCtx
    snap: MarineWarningSnapshot | None
    health: tuple[bool, bool]
    extremes: dict[int, list[TideExtreme]]
    levels: dict[int, list[TideForecast]]
    observed: dict[tuple[int, Metric], list[OceanReading]]
    forecast: dict[tuple[int, Metric], list[OceanReading]]
    forecast_last: dict[tuple[int, Metric], datetime]
    fishing: dict[int, list[FishingIndex]]
    restrictions: dict[int, list]


def prefetch(db: Session, places: list[Place], day: date) -> Prefetch:
    lo, hi = kst_day_range(day)
    now = utcnow()
    ids: dict[StationRole, set[int]] = defaultdict(set)
    for p in places:
        for ps in p.stations:
            ids[ps.role].add(ps.station_id)

    def grouped(rows, key):
        out: dict = defaultdict(list)
        for r in rows:
            out[key(r)].append(r)
        return out

    tide = sorted(ids[StationRole.TIDE])
    extremes = grouped(
        db.scalars(
            select(TideExtreme)
            .where(TideExtreme.station_id.in_(tide), TideExtreme.t >= lo, TideExtreme.t < hi)
            .order_by(TideExtreme.station_id, TideExtreme.t)
        ) if tide else [],
        lambda r: r.station_id,
    )
    levels = grouped(
        db.scalars(
            select(TideForecast)
            .where(TideForecast.station_id.in_(tide), TideForecast.t >= lo, TideForecast.t < hi)
            .order_by(TideForecast.station_id, TideForecast.t)
        ) if tide else [],
        lambda r: r.station_id,
    )
    ocean = sorted(ids[StationRole.OCEAN])
    observed = grouped(
        db.scalars(
            select(OceanReading)
            .where(
                OceanReading.station_id.in_(ocean),
                OceanReading.metric.in_([m for m, _ in OCEAN_METRICS]),
                OceanReading.kind == DataKind.OBSERVED,
                OceanReading.t >= lo,
                OceanReading.t < min(hi, now),
            )
            .order_by(OceanReading.station_id, OceanReading.metric, OceanReading.t)
        ) if ocean and lo <= now else [],
        lambda r: (r.station_id, r.metric),
    )
    fc = sorted(ids[StationRole.FORECAST])
    fc_metrics = [*FORECAST_METRICS, *(m for m, _ in WEATHER_FORECAST_METRICS)]
    forecast = grouped(
        db.scalars(
            select(OceanReading)
            .where(
                OceanReading.station_id.in_(fc),
                OceanReading.metric.in_(fc_metrics),
                OceanReading.kind == DataKind.FORECAST,
                OceanReading.t >= lo,
                OceanReading.t < hi,
            )
            .order_by(OceanReading.station_id, OceanReading.metric, OceanReading.t)
        ) if fc else [],
        lambda r: (r.station_id, r.metric),
    )
    forecast_last = {
        (sid, Metric(m)): t
        for sid, m, t in (
            db.execute(
                select(OceanReading.station_id, OceanReading.metric, func.max(OceanReading.t))
                .where(
                    OceanReading.station_id.in_(fc),
                    OceanReading.metric.in_([m for m, _ in WEATHER_FORECAST_METRICS]),
                    OceanReading.kind == DataKind.FORECAST,
                )
                .group_by(OceanReading.station_id, OceanReading.metric)
            ) if fc else []
        )
    }
    fi = sorted(ids[StationRole.FISHING_INDEX])
    fishing = grouped(
        db.scalars(
            select(FishingIndex)
            .where(FishingIndex.station_id.in_(fi), FishingIndex.day == day)
            .order_by(FishingIndex.id)
        ) if fi else [],
        lambda r: r.station_id,
    )
    snap = latest_snapshot(db)
    return Prefetch(
        day=day,
        lo=lo,
        hi=hi,
        now=now,
        loc=location_ctx(db),
        snap=snap,
        health=collection_health(snap.fetched_at if snap else None),
        extremes=extremes,
        levels=levels,
        observed=observed,
        forecast=forecast,
        forecast_last=forecast_last,
        fishing=fishing,
        restrictions=regulation.load(db, [p.id for p in places]),
    )


def date_range() -> DateRangeOut:
    s = get_settings()
    today = today_kst()
    return DateRangeOut(
        today=today,
        min=today - timedelta(days=s.compare_days_back),
        max=today + timedelta(days=s.compare_days_ahead),
    )


def _check_day(day: date) -> None:
    rng = date_range()
    if not (rng.min <= day <= rng.max):
        raise HTTPException(status_code=400, detail=f"조회 가능한 날짜는 {rng.min} ~ {rng.max} 입니다")


def _load_place(db: Session, place_id: int) -> Place:
    p = db.scalar(
        select(Place)
        .where(Place.id == place_id, Place.is_active.is_(True))
        .options(selectinload(Place.region), selectinload(Place.stations).selectinload(PlaceStation.station))
    )
    if p is None:
        raise HTTPException(status_code=400, detail="지원하지 않는 장소입니다")
    return p


def compare(db: Session, place_a: int, place_b: int, day: date) -> CompareOut:
    if place_a == place_b:
        raise HTTPException(status_code=400, detail="서로 다른 두 장소를 선택해 주세요")
    _check_day(day)
    places = [_load_place(db, pid) for pid in (place_a, place_b)]
    return CompareOut(
        date=day,
        generated_at=utcnow(),
        places=[_place_compare(db, p, day, pf) for pf in [prefetch(db, places, day)] for p in places],
        disclaimer=DISCLAIMER,
    )


def conditions(db: Session, place_id: int, day: date) -> PlaceConditionsOut:
    """장소 1곳의 환경조건 (홈 화면 요약용). 비교와 같은 규칙으로 계열을 만든다"""
    _check_day(day)
    return PlaceConditionsOut(
        date=day,
        generated_at=utcnow(),
        place=_place_compare(db, _load_place(db, place_id), day),
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


def _forecast_series(pf: Prefetch, ps: PlaceStation | None, metric: Metric, unit: str) -> SeriesOut:
    if ps is None:
        return _unavailable(metric.value, unit, DataKind.FORECAST, "NO_STATION")
    source = SourceOut(
        agency=KMA_AGENCY,
        dataset=KMA_DATASET,
        station_code=ps.station.external_id,
        station_name=ps.station.name,
        distance_km=ps.distance_km,
    )
    rows = pf.forecast.get((ps.station_id, metric), [])
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


def _weather_series(pf: Prefetch, ps: PlaceStation | None, metric: Metric, unit: str) -> SeriesOut:
    """기온·강수확률·하늘·강수형태. 받아 둔 예보가 그날 마지막 시각(23시)까지 닿지 않으면
    (예: 예보 범위 밖 날짜의 00시 한 점) 하루 예보처럼 보이지 않도록 「자료 없음」으로 낸다"""
    out = _forecast_series(pf, ps, metric, unit)
    if out.status != "ok" or ps is None:
        return out
    last = pf.forecast_last.get((ps.station_id, metric))
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    if last is None or last < pf.hi - timedelta(hours=1):
        return _unavailable(metric.value, unit, DataKind.FORECAST, "NO_DATA", out.source)
    return out


def _location_check_out(db: Session, place: Place, day: date, pf: Prefetch) -> PlaceCompareOut:
    """좌표가 의심되는 낚시터: 다른 지역 자료가 붙지 않도록 해황 자료를 연결하지 않는다"""
    reason = "LOCATION_CHECK"
    series = [
        _unavailable("tide_extreme", "cm", DataKind.FORECAST, reason),
        _unavailable("tide_level", "cm", DataKind.FORECAST, reason),
    ]
    for metric, unit in OCEAN_METRICS:
        series.append(_unavailable(metric.value, unit, DataKind.OBSERVED, reason))
        if metric in FORECAST_METRICS:
            series.append(_unavailable(metric.value, unit, DataKind.FORECAST, reason))
    for metric, unit in WEATHER_FORECAST_METRICS:
        series.append(_unavailable(metric.value, unit, DataKind.FORECAST, reason))
    out = place_out(db, place, pf.loc)
    out.location_suspect = True
    return PlaceCompareOut(
        place=out,
        region_name=place.region.name,
        regulation=evaluate(db, place.id, day, pf.restrictions.get(place.id, [])),
        warning=WarningOut(level="unknown", status="location_check", reason="LOCATION_CHECK"),
        fishing_index=FishingIndexOut(status="unavailable", reason=reason),
        series=series,
    )


def reference_warning(db: Session, place: Place, pf: Prefetch | None = None) -> WarningOut:
    """좌표 불일치 의심 곳의 특보: 등록 주소 기준 — 참고용.
    실제 낚시 위치의 특보는 확인되지 않았으므로 「특보 없음」으로 표현하지 않는다
    (주소 기준 none → unknown). 주소 기준 특보·예비특보가 있으면 그대로 알린다 (안전 쪽)."""
    w = evaluate_warning(db, place, pf.snap, pf.health) if pf else evaluate_warning(db, place)
    w.reference_only = True
    w.address_level = w.level
    if w.level == "none":
        w.level, w.reason = "unknown", "LOCATION_REVIEW"
    w.note = (
        f"참고용 — 등록 주소({place.region.name}) 기준 해역({'·'.join(w.seas) or '확인 불가'})의 특보예요. "
        "실제 낚시 위치에 적용되는 특보는 아직 확인되지 않았어요. "
        "주소 기준으로 특보가 없어도 실제 위치에 특보가 없다는 뜻은 아니에요."
    )
    return w


def _location_review_out(db: Session, place: Place, day: date, pf: Prefetch) -> PlaceCompareOut:
    """좌표 불일치 의심(C등급 유지·추천 보류): 좌표로 연결한 자료(파고·풍속 예보 격자, 부이, 조위관측소,
    바다낚시지수)는 판단을 보류한다. 해상 특보는 등록 주소 기준이라 그대로 보여주되 한계를 함께 알린다"""
    reason = "LOCATION_REVIEW"
    series = [
        _unavailable("tide_extreme", "cm", DataKind.FORECAST, reason),
        _unavailable("tide_level", "cm", DataKind.FORECAST, reason),
    ]
    for metric, unit in OCEAN_METRICS:
        series.append(_unavailable(metric.value, unit, DataKind.OBSERVED, reason))
        if metric in FORECAST_METRICS:
            series.append(_unavailable(metric.value, unit, DataKind.FORECAST, reason))
    for metric, unit in WEATHER_FORECAST_METRICS:
        series.append(_unavailable(metric.value, unit, DataKind.FORECAST, reason))
    warning = reference_warning(db, place, pf)
    return PlaceCompareOut(
        place=place_out(db, place, pf.loc),
        region_name=place.region.name,
        regulation=evaluate(db, place.id, day, pf.restrictions.get(place.id, [])),
        warning=warning,
        fishing_index=FishingIndexOut(status="unavailable", reason=reason),
        series=series,
    )


def _place_compare(db: Session, place: Place, day: date, pf: Prefetch | None = None) -> PlaceCompareOut:
    """pf 를 주면 미리 읽어 둔 자료로 계산한다 (없으면 이 장소만 읽음 — 규칙은 같다)"""
    if pf is None:
        pf = prefetch(db, [place], day)
    if place.id in pf.loc.suspects:
        return _location_check_out(db, place, day, pf)
    if place.id in pf.loc.holds:
        return _location_review_out(db, place, day, pf)
    by_role = {ps.role: ps for ps in place.stations}
    lo, now = pf.lo, pf.now
    series: list[SeriesOut] = []

    # --- 조석: 고·저조 (예보) ---
    tide = by_role.get(StationRole.TIDE)
    if tide is None:
        series.append(_unavailable("tide_extreme", "cm", DataKind.FORECAST, "NO_STATION"))
        series.append(_unavailable("tide_level", "cm", DataKind.FORECAST, "NO_STATION"))
    elif same_sea(db, place, tide.station_id, pf.loc) is False:
        # 거리가 가까워도 다른 바다를 보는 조위관측소면 대표 자료로 쓰지 않는다
        series.append(
            _unavailable(
                "tide_extreme", "cm", DataKind.FORECAST, "DIFFERENT_SEA", _source(tide, EP_TIDE_EXTREME)
            )
        )
        series.append(
            _unavailable(
                "tide_level", "cm", DataKind.FORECAST, "DIFFERENT_SEA", _source(tide, EP_TIDE_HOURLY)
            )
        )
    else:
        ext = pf.extremes.get(tide.station_id, [])
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

        lv = pf.levels.get(tide.station_id, [])
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
            rows = pf.observed.get((ocean.station_id, metric), [])
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
            series.append(_forecast_series(pf, by_role.get(StationRole.FORECAST), metric, unit))

    for metric, unit in WEATHER_FORECAST_METRICS:
        series.append(_weather_series(pf, by_role.get(StationRole.FORECAST), metric, unit))

    return PlaceCompareOut(
        place=place_out(db, place, pf.loc),
        region_name=place.region.name,
        regulation=evaluate(db, place.id, day, pf.restrictions.get(place.id, [])),
        warning=evaluate_warning(db, place, pf.snap, pf.health),
        fishing_index=_fishing_index(pf, by_role.get(StationRole.FISHING_INDEX)),
        series=series,
    )


_PERIOD_ORDER = {"오전": 0, "오후": 1, "일": 2}
_SPECIES_LAST = {"기타어종", "-"}
# 일부 지점(선상 등)은 어종 구분 없이 「-」로 지수를 발표한다 → 버리지 않고 「어종 공통」으로 표시
SPECIES_COMMON = "어종 공통"


def _fishing_index(pf: Prefetch, ps: PlaceStation | None) -> FishingIndexOut:
    """공식 바다낚시지수를 그대로 전달한다. 지점이 멀면 TOO_FAR (앱이 대신 판정하지 않음)"""
    if ps is None:
        return FishingIndexOut(status="unavailable", reason="NO_STATION")
    source = _source(ps, EP_FISHING_INDEX)
    if ps.distance_km is not None and ps.distance_km > get_settings().fishing_index_max_km:
        return FishingIndexOut(status="unavailable", reason="TOO_FAR", source=source)

    rows = pf.fishing.get(ps.station_id, [])
    if not rows:
        return FishingIndexOut(status="unavailable", reason="NO_DATA", source=source)

    periods: dict[str, list[FishingIndex]] = {}
    for r in rows:
        periods.setdefault(r.period, []).append(r)
    return FishingIndexOut(
        status="ok",
        source=source,
        fetched_at=max(r.fetched_at for r in rows),
        periods=[
            FishingPeriodOut(
                period=period,
                tide_phase=next((r.tide_phase for r in items if r.tide_phase), None),
                items=[
                    FishingSpeciesOut(
                        species=SPECIES_COMMON if r.species == "-" else r.species,
                        index=r.index,
                        min_wave_m=r.min_wave_m,
                        max_wave_m=r.max_wave_m,
                        min_water_temp=r.min_water_temp,
                        max_water_temp=r.max_water_temp,
                        min_wind_ms=r.min_wind_ms,
                        max_wind_ms=r.max_wind_ms,
                    )
                    for r in sorted(items, key=lambda r: (r.species in _SPECIES_LAST, r.species))
                ],
            )
            for period, items in sorted(periods.items(), key=lambda kv: _PERIOD_ORDER.get(kv[0], 9))
        ],
    )


def _unavailable(
    metric: str, unit: str, kind: DataKind, reason: str, source: SourceOut | None = None
) -> SeriesOut:
    return SeriesOut(metric=metric, unit=unit, kind=kind, status="unavailable", reason=reason, source=source)
