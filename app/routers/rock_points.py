"""참고 포인트: 해양수산부 갯바위낚시포인트 (탐험 1단계, 2026-11-19).

- seeds/rock_points.json (scripts/build_rock_points.py 로 생성)을 그대로 준다
- 해경 출입통제구역 200m 안은 이미 뺐고, 연안사고 위험구역 100m 안은 danger 에 적혀 있다
- 낚시 허용·접근 여부는 확인되지 않은 「참고 위치」 — 추천·인증 대상이 아니다
- 자료가 바뀌지 않으므로 하루 캐시
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Response
from pydantic import BaseModel

router = APIRouter(tags=["places"])
_FILE = Path(__file__).resolve().parent.parent.parent / "seeds" / "rock_points.json"


class RockCatchOut(BaseModel):
    species: str
    methods: list[str]


class RockPointOut(BaseModel):
    id: int
    name: str
    area: str
    admin: str
    lat: float
    lon: float
    depth: str | None = None
    bottom: str | None = None
    tide: str | None = None
    catches: list[RockCatchOut] = []
    danger: str | None = None


class RockPointsOut(BaseModel):
    source: str
    excluded: str
    notice: str
    points: list[RockPointOut]


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"source": "", "excluded": "", "notice": "", "points": []}


@router.get("/rock-points", response_model=RockPointsOut)
def rock_points(response: Response):
    response.headers["Cache-Control"] = "public, max-age=86400"
    return _data()
