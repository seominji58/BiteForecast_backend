"""낚시터 실제 사진 (한국관광공사 TourAPI 매칭) — 2026-11-18.

- seeds/tour_photos.json (scripts/match_tour_photos.py 로 생성)을 읽어 준다
- 사진은 관광공사 이미지 주소 그대로
- 공공누리 제3유형: 출처(한국관광공사) 표시 · 변경 금지 → 앱은 자르지 않고 원본 비율로 보여준다
- 매칭된 낚시터만 사진이 있다 (거리 + 이름이 함께 맞는 곳만, 엉뚱한 사진을 붙이지 않음)
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["places"])
_FILE = Path(__file__).resolve().parent.parent.parent / "seeds" / "tour_photos.json"
_SOURCE = "한국관광공사"
_LICENSE = "공공누리 제3유형 (출처 표시·변경 금지)"


class PhotoOut(BaseModel):
    url: str
    thumb: str


class PlacePhotosOut(BaseModel):
    title: str
    source: str
    license: str
    images: list[PhotoOut]


class PhotoIndexOut(BaseModel):
    source: str
    license: str
    # 낚시터 id → 목록용 썸네일 (사진이 있는 곳만)
    thumbs: dict[int, str]


@lru_cache(maxsize=1)
def _data() -> dict[int, dict]:
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {int(k): v for k, v in raw.get("places", {}).items() if v.get("images")}


@router.get("/place-photos", response_model=PhotoIndexOut)
def photo_index():
    return PhotoIndexOut(
        source=_SOURCE, license=_LICENSE, thumbs={k: v["images"][0]["thumb"] for k, v in _data().items()}
    )


@router.get("/places/{place_id}/photos", response_model=PlacePhotosOut)
def place_photos(place_id: int):
    m = _data().get(place_id)
    if not m:
        raise HTTPException(status_code=404, detail="이 낚시터의 사진이 없어요")
    return PlacePhotosOut(
        title=m["title"], source=_SOURCE, license=m.get("license") or _LICENSE, images=m["images"]
    )
