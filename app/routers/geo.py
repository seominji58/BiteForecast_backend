"""지역·장소 검색 (카카오 로컬 키워드 검색 대행) — 2026-11-17.

- 지도에서 「속초 외옹치」 「태안 신진도」처럼 우리 낚시터 목록에 없는 지명으로도 이동할 수 있게
- 카카오 REST 키는 서버에만 둔다. 검색어는 저장·기록하지 않는다
- 같은 검색어는 1시간 동안 메모리 캐시 (카카오 하루 호출 한도 보호)
"""

import time

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(tags=["geo"])
_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
_TTL = 3600
_cache: dict[str, tuple[float, list]] = {}


class GeoPlaceOut(BaseModel):
    name: str
    address: str
    lat: float
    lon: float
    category: str | None = None


@router.get("/geo/search", response_model=list[GeoPlaceOut])
def search(q: str = Query(min_length=2, max_length=40)):
    key = get_settings().kakao_rest_key
    if not key:
        raise HTTPException(status_code=503, detail="지역 검색을 지금 쓸 수 없어요")
    q = q.strip()
    hit = _cache.get(q)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    try:
        r = httpx.get(_URL, params={"query": q, "size": 8}, headers={"Authorization": f"KakaoAK {key}"}, timeout=5)
        r.raise_for_status()
        docs = r.json().get("documents", [])
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=502, detail="지역 검색에 실패했어요. 잠시 후 다시 시도해 주세요") from None
    out = [
        GeoPlaceOut(
            name=d.get("place_name") or "",
            address=d.get("road_address_name") or d.get("address_name") or "",
            lat=float(d["y"]),
            lon=float(d["x"]),
            category=(d.get("category_name") or "").split(" > ")[-1] or None,
        )
        for d in docs
        if d.get("x") and d.get("y")
    ]
    if len(_cache) > 500:
        _cache.clear()
    _cache[q] = (time.monotonic(), out)
    return out
