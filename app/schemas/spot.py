"""내 낚시터 (사용자가 직접 찍은 비공개 포인트) 입출력"""

from datetime import datetime

from pydantic import BaseModel, Field


class SpotIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    lat: float = Field(ge=32.0, le=39.5)  # 한반도 바다 범위 밖 좌표는 받지 않는다
    lon: float = Field(ge=124.0, le=132.0)
    memo: str | None = Field(default=None, max_length=500)


class SpotPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    memo: str | None = Field(default=None, max_length=500)


class NearPlace(BaseModel):
    """가장 가까운 공식 낚시터 — 해황·물때는 이곳 기준으로 본다"""

    id: int
    name: str
    km: float


class SpotOut(BaseModel):
    id: int
    name: str
    lat: float
    lon: float
    memo: str | None
    created_at: datetime
    near: NearPlace | None
