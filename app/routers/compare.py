from datetime import date

from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
from app.clients.khoa import AGENCY, DATASET_NAMES, EP_BUOY, EP_TIDE_EXTREME, EP_TIDE_HOURLY
from app.models import Place
from app.models.enums import DataKind
from app.schemas.compare import CompareOut, DataSourceOut, DateRangeOut, RegulationOut
from app.services import compare as svc
from app.services.regulation import evaluate

router = APIRouter(tags=["compare"])


@router.get("/compare", response_model=CompareOut)
def compare(place_a: int, place_b: int, date: date, db: DbSession):
    """A/B 두 장소의 같은 날짜 환경조건 비교 (FR-02~05, FR-07)"""
    return svc.compare(db, place_a, place_b, date)


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
            agency="기상청", dataset="단기예보 (파고·풍속)", kind=DataKind.FORECAST, connected=True
        ),
    ]


@router.get("/places/{place_id}/regulation", response_model=RegulationOut)
def regulation(place_id: int, date: date, db: DbSession):
    if db.get(Place, place_id) is None:
        raise HTTPException(status_code=404, detail="장소를 찾을 수 없습니다")
    return evaluate(db, place_id, date)
