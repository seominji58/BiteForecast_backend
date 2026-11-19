"""낚시터 카카오 장소 링크·도로명 주소 (카카오 로컬 매칭) — 2026-11-19.

- seeds/kakao_places.json (scripts/match_kakao_places.py 로 생성)을 읽어 준다
- 이름·시군구·거리·업종이 함께 맞은 곳만 있다. 사진·리뷰는 앱이 카카오맵 장소 페이지로 보낸다
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["places"])
_FILE = Path(__file__).resolve().parent.parent.parent / "seeds" / "kakao_places.json"


class PlaceKakaoOut(BaseModel):
    name: str
    url: str
    road_address: str
    category: str
    phone: str | None = None
    # 좌표를 카카오 위치로 보정한 곳인지
    moved: bool
    source: str = "카카오"


@lru_cache(maxsize=1)
def _data() -> dict[int, dict]:
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {int(k): v for k, v in raw.get("places", {}).items()}


@router.get("/places/{place_id}/kakao", response_model=PlaceKakaoOut)
def place_kakao(place_id: int):
    m = _data().get(place_id)
    if not m:
        raise HTTPException(status_code=404, detail="카카오 장소와 연결되지 않은 낚시터예요")
    return PlaceKakaoOut(**{k: m.get(k) for k in PlaceKakaoOut.model_fields if k != "source"})
