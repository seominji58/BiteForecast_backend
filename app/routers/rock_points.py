"""참고 포인트: 해양수산부 갯바위낚시포인트 (탐험 1단계, 2026-11-19).

- seeds/rock_points.json (scripts/build_rock_points.py 로 생성)을 그대로 준다
- 해경 출입통제구역 200m 안은 이미 뺐고, 연안사고 위험구역 100m 안은 danger 에 적혀 있다
- 낚시 허용·접근 여부는 확인되지 않은 「참고 위치」 — 추천·인증 대상이 아니다
- 자료가 바뀌지 않으므로 하루 캐시
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.routers.nearby import NearbyOut, search_around
from app.services.near_address import near

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
    # 좌표 근처 주소 (카카오 좌표→주소). region 이면 동·리 이름만 → 앱에서 「근처」
    near_address: str | None = None
    near_address_kind: Literal["address", "region"] | None = None


class RockPointsOut(BaseModel):
    source: str
    excluded: str
    notice: str
    points: list[RockPointOut]


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        d = json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"source": "", "excluded": "", "notice": "", "points": []}
    for p in d["points"]:
        hit = near("rock", p["id"], p["lat"], p["lon"])
        if hit:
            p["near_address"], p["near_address_kind"] = hit
    return d


@router.get("/rock-points", response_model=RockPointsOut)
def rock_points(response: Response):
    response.headers["Cache-Control"] = "public, max-age=86400"
    return _data()


@router.get("/rock-points/{point_id}/nearby", response_model=NearbyOut)
def rock_point_nearby(point_id: int):
    """갯바위 포인트 주변 낚시점·낚시배 (낚시터와 같은 카카오 반경 검색)"""
    p = next((p for p in _data()["points"] if p["id"] == point_id), None)
    if p is None:
        raise HTTPException(status_code=404, detail="포인트를 찾을 수 없습니다")
    return search_around(f"r{point_id}", p["lat"], p["lon"])
