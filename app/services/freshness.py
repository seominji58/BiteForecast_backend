"""수집 자료의 신선도 (마지막 수집 시각과 상태).

수집기가 멈추면 오래된 자료를 최신처럼 보여주지 않도록,
화면이 「마지막 갱신 시각」과 「오래됨」을 함께 받는다.
읽기 전용 — 수집 방식·운영 환경은 바꾸지 않는다.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import FishingIndex, MarineWarningSnapshot, OceanReading, TideForecast
from app.models.base import utcnow
from app.models.enums import DataKind
from app.schemas.summary import DataStatusOut

# 자료별 기준 (발표·갱신 주기에 맞춤)
# - 단기예보: 3시간마다 발표(02·05·…·23시), 발표 10분 뒤 제공, 수집 1시간 주기
#   → 마지막 「발표 시각」이 3시간 + 10분 + 1시간 넘게 지나면 발표분을 놓친 것 (수집 시각으로 보면
#     같은 발표분은 다시 받지 않아 정상인데도 오래됨으로 깜빡일 수 있다)
# - 해상 특보: 수시 발표라 발표 시각은 며칠 전일 수 있다 → 「수집 시각」 기준, 매시간 받으므로 3시간
FORECAST_STALE_AFTER = timedelta(hours=4, minutes=10)
WARNING_STALE_AFTER = timedelta(hours=3)
STALE_AFTER = WARNING_STALE_AFTER  # 하위 호환 (응답의 stale_after_hours)


def data_status(db: Session) -> DataStatusOut:
    forecast = db.scalar(
        select(func.max(OceanReading.fetched_at)).where(OceanReading.kind == DataKind.FORECAST)
    )
    forecast_issued = db.scalar(
        select(func.max(OceanReading.issued_at)).where(OceanReading.kind == DataKind.FORECAST)
    )
    # 예보 유효 범위: 받아 둔 예보의 마지막 시각 (이 시각 이후 날짜는 예보 없음)
    forecast_until = db.scalar(select(func.max(OceanReading.t)).where(OceanReading.kind == DataKind.FORECAST))
    buoy = db.scalar(select(func.max(OceanReading.fetched_at)).where(OceanReading.kind == DataKind.OBSERVED))
    warning = db.scalar(select(func.max(MarineWarningSnapshot.fetched_at)))
    tide = db.scalar(select(func.max(TideForecast.fetched_at)))
    index = db.scalar(select(func.max(FishingIndex.fetched_at)))

    now = utcnow()

    # 출조 탐색은 예보(파고·풍속)와 특보로 판단 → 둘 중 하나라도 오래되면 「오래됨」
    forecast_old = forecast_issued is None or now - forecast_issued > FORECAST_STALE_AFTER
    warning_old = warning is None or now - warning > WARNING_STALE_AFTER
    stale = forecast_old or warning_old
    reason = None
    if forecast_issued is None or warning is None:
        reason = "아직 수집한 자료가 없어요"
    elif forecast_old:
        hours = int((now - forecast_issued).total_seconds() // 3600)
        reason = f"기상청 예보가 {hours}시간 넘게 새로 발표·수집되지 않았어요"
    elif warning_old:
        hours = int((now - warning).total_seconds() // 3600)
        reason = f"해상 특보를 {hours}시간 넘게 확인하지 못했어요"
    return DataStatusOut(
        forecast_fetched_at=forecast,
        forecast_issued_at=forecast_issued,
        forecast_valid_until=forecast_until,
        warning_fetched_at=warning,
        buoy_fetched_at=buoy,
        tide_fetched_at=tide,
        index_fetched_at=index,
        stale=stale,
        stale_reason=reason,
        stale_after_hours=int(STALE_AFTER.total_seconds() // 3600),
    )
