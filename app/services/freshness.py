"""수집 자료의 신선도 (마지막 수집 시각과 상태).

수집기가 멈추면 오래된 자료를 최신처럼 보여주지 않도록,
화면이 「마지막 갱신 시각」과 「오래됨」을 함께 받는다.
읽기 전용 — 수집 방식·운영 환경은 바꾸지 않는다.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import FishingIndex, MarineWarningSnapshot, OceanReading, TideForecast
from app.models.base import utcnow
from app.models.enums import DataKind
from app.schemas.summary import DataStatusOut

# 수집 주기 1시간 기준: 3시간 넘게 새 자료가 없으면 「오래됨」 (특보 판정의 기준과 같다)
STALE_AFTER = timedelta(hours=3)


def data_status(db: Session) -> DataStatusOut:
    forecast = db.scalar(
        select(func.max(OceanReading.fetched_at)).where(OceanReading.kind == DataKind.FORECAST)
    )
    buoy = db.scalar(select(func.max(OceanReading.fetched_at)).where(OceanReading.kind == DataKind.OBSERVED))
    warning = db.scalar(select(func.max(MarineWarningSnapshot.fetched_at)))
    tide = db.scalar(select(func.max(TideForecast.fetched_at)))
    index = db.scalar(select(func.max(FishingIndex.fetched_at)))

    now = utcnow()

    def old(t: datetime | None) -> bool:
        return t is None or now - t > STALE_AFTER

    # 출조 탐색은 예보(파고·풍속)와 특보로 판단 → 둘 중 하나라도 오래되면 「오래됨」
    stale = old(forecast) or old(warning)
    reason = None
    if forecast is None or warning is None:
        reason = "아직 수집한 자료가 없어요"
    elif stale:
        oldest = min(forecast, warning)
        hours = int((now - oldest).total_seconds() // 3600)
        reason = f"자료가 {hours}시간 넘게 갱신되지 않았어요"
    return DataStatusOut(
        forecast_fetched_at=forecast,
        warning_fetched_at=warning,
        buoy_fetched_at=buoy,
        tide_fetched_at=tide,
        index_fetched_at=index,
        stale=stale,
        stale_reason=reason,
        stale_after_hours=int(STALE_AFTER.total_seconds() // 3600),
    )
