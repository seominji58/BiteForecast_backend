from datetime import date

from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
from app.clients.khoa import AGENCY, DATASET_NAMES, EP_BUOY, EP_FISHING_INDEX, EP_TIDE_EXTREME, EP_TIDE_HOURLY
from app.models import Place
from app.models.enums import DataKind
from app.schemas.compare import CompareOut, DataSourceOut, DateRangeOut, PlaceConditionsOut, RegulationOut
from app.services import compare as svc
from app.services.regulation import evaluate

router = APIRouter(tags=["compare"])


@router.get("/compare", response_model=CompareOut)
def compare(place_a: int, place_b: int, date: date, db: DbSession):
    """A/B 두 장소의 같은 날짜 환경조건 비교 (FR-02~05, FR-07)"""
    return svc.compare(db, place_a, place_b, date)


@router.get("/places/{place_id}/conditions", response_model=PlaceConditionsOut)
def place_conditions(place_id: int, date: date, db: DbSession):
    """장소 1곳의 같은 날짜 환경조건 (홈 화면 요약)"""
    return svc.conditions(db, place_id, date)


@router.get("/meta/date-range", response_model=DateRangeOut)
def date_range():
    return svc.date_range()


@router.get("/meta/sources", response_model=list[DataSourceOut])
def sources():
    """데이터 출처 목록 (FR-15, SCR-07)"""
    return [
        DataSourceOut(
            agency=AGENCY, dataset=DATASET_NAMES[EP_TIDE_EXTREME], kind=DataKind.FORECAST, connected=True
        ),
        DataSourceOut(
            agency=AGENCY, dataset=DATASET_NAMES[EP_TIDE_HOURLY], kind=DataKind.FORECAST, connected=True
        ),
        DataSourceOut(agency=AGENCY, dataset=DATASET_NAMES[EP_BUOY], kind=DataKind.OBSERVED, connected=True),
        DataSourceOut(
            agency=AGENCY,
            dataset=DATASET_NAMES[EP_FISHING_INDEX],
            kind=DataKind.FORECAST,
            connected=True,
            note="기관이 발표한 5단계 지수를 그대로 표시 (앱 자체 판정 아님)",
        ),
        DataSourceOut(
            agency="기상청", dataset="단기예보 (파고·풍속)", kind=DataKind.FORECAST, connected=True
        ),
        DataSourceOut(
            agency="지방자치단체 (공공데이터포털)",
            dataset="전국낚시터정보표준데이터 (낚시터 위치·요금·시설)",
            kind=DataKind.OBSERVED,
            connected=True,
            note="신고된 바다 낚시터 목록",
        ),
    ]


@router.get("/places/{place_id}/regulation", response_model=RegulationOut)
def regulation(place_id: int, date: date, db: DbSession):
    if db.get(Place, place_id) is None:
        raise HTTPException(status_code=404, detail="장소를 찾을 수 없습니다")
    return evaluate(db, place_id, date)
