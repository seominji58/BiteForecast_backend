"""사진으로 어종 찾기 (로그인 필요, 하루 횟수 제한). 사진은 저장하지 않는다"""

from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Species
from app.services import fish_id as svc

router = APIRouter(prefix="/fish-id", tags=["fish-id"])

NOTICE = (
    "AI가 사진으로 추정한 결과예요. 틀릴 수 있으니 최종 어종은 직접 골라 주세요. "
    "먹어도 되는지는 알려 드리지 않아요 — 모르는 물고기는 먹지 마세요."
)


def is_puffer(name: str) -> bool:
    """복어류 (자주복·참복·까치복·졸복·복섬 등). 전복은 조개라 제외"""
    base = name.split("(")[0].strip()
    return "복어" in name or "복섬" in name or (base.endswith("복") and base not in ("전복", "까막전복"))


class CandidateOut(BaseModel):
    code: str | None
    name: str
    confidence: Literal["높음", "보통", "낮음"]
    features: str


class FishIdOut(BaseModel):
    is_fish: bool
    candidates: list[CandidateOut]
    photo_tip: str | None
    notice: str
    remaining: int


class FishIdStatus(BaseModel):
    enabled: bool
    remaining: int


@router.get("/status", response_model=FishIdStatus)
def status(user: CurrentUser):
    return FishIdStatus(enabled=svc.enabled(), remaining=svc.remaining(user.id))


@router.post("", response_model=FishIdOut)
async def identify(user: CurrentUser, db: DbSession, file: Annotated[UploadFile, File()]):
    if not svc.enabled():
        raise HTTPException(status_code=503, detail="사진으로 어종 찾기가 아직 준비 중이에요")
    raw = await file.read()
    try:
        jpeg = svc.prepare_image(raw)
        left = svc.take_quota(user.id)
    except svc.FishIdError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from None
    species = [(c, n) for c, n in db.execute(select(Species.code, Species.name_ko).order_by(Species.code))]
    try:
        out = svc.identify(jpeg, species)
    except svc.FishIdError as e:
        svc.give_back(user.id)
        raise HTTPException(status_code=e.status, detail=e.message) from None
    cands = [CandidateOut(**c) for c in out.get("candidates", [])[:3]]
    notice = NOTICE
    if any(is_puffer(c.name) for c in cands):
        notice = "⚠ 복어류는 독이 있어요. 절대 먹지 말고 바로 놓아주세요. " + NOTICE
    return FishIdOut(
        is_fish=bool(out.get("is_fish")),
        candidates=cands,
        photo_tip=out.get("photo_tip"),
        notice=notice,
        remaining=left,
    )
