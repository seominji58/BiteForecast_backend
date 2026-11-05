"""일지 ↔ 당시 환경정보 연결 (FR-10).

출조 장소에 매핑된 관측소에서, 출조 시각 ±1시간 안의 가장 가까운 값을 지표마다 찾아 스냅샷으로 저장한다.
- 실측(observed)이 있으면 실측을, 없으면 예보(forecast)를 쓴다. 어느 쪽인지 kind 로 함께 저장한다
- 값을 찾지 못하면 value/kind 를 None 으로 저장한다 (0 으로 채우지 않음, TC-02)
- 화면에서는 "당시 인근 관측소 기록"으로 안내하고 현장 조건으로 단정하지 않는다
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Journal, JournalEnvSnapshot, OceanReading, PlaceStation, TideForecast
from app.models.enums import DataKind, Metric, StationRole

WINDOW = timedelta(hours=1)  # 명세 D-10

OCEAN_METRICS: list[tuple[Metric, str]] = [
    (Metric.WAVE_HEIGHT, "m"),
    (Metric.WIND_SPEED, "m/s"),
    (Metric.WATER_TEMP, "°C"),
]


def _nearest(rows, t: datetime):
    """t 에 가장 가까운 행. 같은 거리면 가장 최근 발표(issued_at) 우선"""
    if not rows:
        return None
    return min(rows, key=lambda r: (abs(r.t - t), -r.issued_at.timestamp()))


def link_environment(db: Session, journal: Journal) -> None:
    journal.env_snapshots.clear()
    db.flush()

    mappings = {
        ps.role: ps
        for ps in db.scalars(
            select(PlaceStation)
            .where(PlaceStation.place_id == journal.place_id)
            .options(selectinload(PlaceStation.station))
        ).all()
    }
    t = journal.fished_at
    lo, hi = t - WINDOW, t + WINDOW

    # 조위: 예측값만 존재 (FR-03)
    tide_ps = mappings.get(StationRole.TIDE)
    tide_row = None
    if tide_ps:
        tide_row = _nearest(
            db.scalars(
                select(TideForecast).where(
                    TideForecast.station_id == tide_ps.station_id, TideForecast.t.between(lo, hi)
                )
            ).all(),
            t,
        )
    journal.env_snapshots.append(
        _snapshot(Metric.TIDE_LEVEL, "cm", tide_ps, tide_row, tide_row.level_cm if tide_row else None)
    )

    # 파고·풍속·수온: 실측 우선, 없으면 예보
    ocean_ps = mappings.get(StationRole.OCEAN)
    for metric, unit in OCEAN_METRICS:
        row = None
        if ocean_ps:
            rows = db.scalars(
                select(OceanReading).where(
                    OceanReading.station_id == ocean_ps.station_id,
                    OceanReading.metric == metric,
                    OceanReading.t.between(lo, hi),
                    OceanReading.value.is_not(None),
                )
            ).all()
            row = _nearest([r for r in rows if r.kind == DataKind.OBSERVED], t) or _nearest(
                [r for r in rows if r.kind == DataKind.FORECAST], t
            )
        journal.env_snapshots.append(_snapshot(metric, unit, ocean_ps, row, row.value if row else None))

    db.flush()


def _snapshot(
    metric: Metric, unit: str, ps: PlaceStation | None, row, value: float | None
) -> JournalEnvSnapshot:
    kind = None
    if row is not None:
        kind = row.kind if isinstance(row, OceanReading) else DataKind.FORECAST
    return JournalEnvSnapshot(
        metric=metric,
        kind=kind,
        value=value,
        unit=unit,
        value_time=row.t if row is not None else None,
        station_id=ps.station_id if ps else None,
        distance_km=ps.distance_km if ps else None,
        source_agency=ps.station.provider if ps else None,
    )
