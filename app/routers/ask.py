"""입질예보에게 묻기 (로그인 필요, 하루 횟수 제한). 대화는 저장하지 않는다 — 앱이 최근 대화를 함께 보낸다"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.models import Place
from app.services import ask as svc
from app.services import fish_id

router = APIRouter(prefix="/ask", tags=["ask"])


class Msg(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=600)


class AskIn(BaseModel):
    messages: list[Msg] = Field(min_length=1, max_length=12)
    place_id: int | None = None


class PlaceRef(BaseModel):
    place_id: int
    name: str


class AskOut(BaseModel):
    answer: str
    places: list[PlaceRef]
    remaining: int


class AskStatus(BaseModel):
    enabled: bool
    remaining: int


@router.get("/status", response_model=AskStatus)
def status(user: CurrentUser):
    on = get_settings().ask_enabled and fish_id.enabled()
    return AskStatus(enabled=on, remaining=svc.remaining(user.id))


@router.post("", response_model=AskOut)
def ask(body: AskIn, user: CurrentUser, db: DbSession):
    if not (get_settings().ask_enabled and fish_id.enabled()):
        raise HTTPException(status_code=503, detail="입질예보에게 묻기가 아직 준비 중이에요")
    if body.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="마지막은 질문이어야 해요")
    try:
        left = svc.take_quota(user.id)
    except fish_id.FishIdError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from None
    hint = None
    if body.place_id is not None:
        p = db.get(Place, body.place_id)
        hint = p.name if p else None
    history = [m.model_dump() for m in body.messages[-8:]]
    try:
        answer, seen = svc.ask(db, history, hint)
    except fish_id.FishIdError as e:
        svc.give_back(user.id)
        raise HTTPException(status_code=e.status, detail=e.message) from None
    return AskOut(
        answer=answer,
        places=[PlaceRef(place_id=k, name=v) for k, v in list(seen.items())[:3]],
        remaining=left,
    )
