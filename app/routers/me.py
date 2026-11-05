from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.me import MyTitleOut
from app.services.titles import get_my_title

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/title", response_model=MyTitleOut)
def my_title(user: CurrentUser, db: DbSession):
    return get_my_title(db, user)
