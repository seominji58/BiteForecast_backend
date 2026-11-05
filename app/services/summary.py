"""전체 낚시터 해황 요약 (지도·주변 찾기·조건으로 찾기용).

장소마다 상세 비교(_place_compare)와 같은 자료에서 몇 개 값만 뽑는다.
- 실측 최신값과 예보 최댓값을 다른 필드로 둔다 (섞지 않음)
- 앱이 「좋다/나쁘다」를 판정하지 않는다. 조건 판단은 사용자가 정한 기준으로 앱에서 한다
- 수집 주기(1시간)보다 짧게 10분 캐시 — 요청 때 외부 API 를 부르지 않는다 (NFR-06)
"""

import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.timeutil import today_kst
from app.models import Place, PlaceStation
from app.models.base import utcnow
from app.schemas.compare import SeriesOut
from app.schemas.summary import IndexSummaryOut, PlaceSummaryOut, ValueAt
from app.services.compare import _place_compare

KST = ZoneInfo("Asia/Seoul")
_TTL_SECONDS = 600
_cache: dict[date, tuple[float, list[PlaceSummaryOut]]] = {}

_LEVEL_RANK = {"매우좋음": 5, "좋음": 4, "보통": 3, "나쁨": 2, "매우나쁨": 1}


def _find(series: list[SeriesOut], metric: str, kind: str) -> SeriesOut | None:
    return next((s for s in series if s.metric == metric and s.kind == kind and s.status == "ok"), None)


def _latest(s: SeriesOut | None) -> ValueAt | None:
    for p in reversed((s.points or []) if s else []):
        if p.v is not None:
            return ValueAt(v=round(p.v, 1), t=p.t)
    return None


def _peak(s: SeriesOut | None, after: datetime | None) -> ValueAt | None:
    best = None
    for p in (s.points or []) if s else []:
        if p.v is None or (after is not None and p.t < after):
            continue
        if best is None or p.v > best.v:
            best = ValueAt(v=round(p.v, 1), t=p.t)
    return best


def _index(pc) -> IndexSummaryOut | None:
    f = pc.fishing_index
    if f.status != "ok" or not f.periods:
        return None
    hour = datetime.now(KST).hour  # 지수 발표 시간대(오전·오후)는 한국 시간 기준
    want = "오전" if hour < 12 else "오후"
    period = next((p for p in f.periods if p.period == want), None) or next(
        (p for p in f.periods if p.period == "일"), f.periods[0]
    )
    levels = [i.index for i in period.items if i.index]
    if not levels:
        return None
    best = max(levels, key=lambda x: _LEVEL_RANK[x])
    worst = min(levels, key=lambda x: _LEVEL_RANK[x])
    return IndexSummaryOut(
        period=period.period,
        tide_phase=period.tide_phase,
        best=best,
        worst=worst,
        species_count=len(levels),
        station_km=f.source.distance_km if f.source else None,
    )


def summarize(db: Session, day: date) -> list[PlaceSummaryOut]:
    hit = _cache.get(day)
    if hit and time.monotonic() - hit[0] < _TTL_SECONDS:
        return hit[1]

    places = db.scalars(
        select(Place)
        .where(Place.is_active.is_(True))
        .options(
            selectinload(Place.region),
            selectinload(Place.info),
            selectinload(Place.stations).selectinload(PlaceStation.station),
        )
    ).all()
    after = utcnow() if day == today_kst() else None
    out = []
    for place in places:
        pc = _place_compare(db, place, day)
        wave_obs = _find(pc.series, "wave_height", "observed")
        wind_obs = _find(pc.series, "wind_speed", "observed")
        out.append(
            PlaceSummaryOut(
                place_id=place.id,
                warning_level=pc.warning.level,
                warning_types=sorted({m.type for m in pc.warning.active}),
                wave_obs=_latest(wave_obs),
                wave_obs_km=wave_obs.source.distance_km if wave_obs and wave_obs.source else None,
                wave_fc_max=_peak(_find(pc.series, "wave_height", "forecast"), after),
                wind_obs=_latest(wind_obs),
                wind_fc_max=_peak(_find(pc.series, "wind_speed", "forecast"), after),
                temp_obs=_latest(_find(pc.series, "water_temp", "observed")),
                index=_index(pc),
            )
        )
    _cache[day] = (time.monotonic(), out)
    return out
