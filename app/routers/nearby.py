"""낚시터 근처 낚시점·낚시배 (카카오 로컬 키워드 반경 검색 대행) — 2026-11-18.

설계: docs/01_기획/2026-11-17_낚시터_주변플레이스_설계.md (2차)
- 카카오 REST 키는 서버에만. /geo/search 와 같은 방식(메모리 캐시 1시간)
- 분류(category_name)에 「낚시」가 없는 결과는 뺀다 (검색어만 걸린 펜션·민박 등)
- 낚시배는 유료 낚시터(「낚시 > 낚시터」)를 빼고 「낚시」 분류만
- 장비 대여 여부는 카카오 자료로 구분되지 않아 따로 표시하지 않는다 (앱에서 「대여 여부는 전화로 확인」)
- 좌표가 의심(D등급)이거나 없는 낚시터는 거리가 틀릴 수 있어 검색하지 않는다
"""

import time
from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import DbSession
from app.core.config import get_settings
from app.models.place import Place
from app.services.location import suspect_place_ids

router = APIRouter(tags=["places"])
_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
_TTL = 3600
_cache: dict[tuple[str, str], tuple[float, list]] = {}

Kind = Literal["shop", "boat"]
# 종류별 검색어 · 반경(m). 낚시배는 항구에서 출항하므로 넓게
_QUERY: dict[str, tuple[str, int]] = {"shop": ("낚시점", 5000), "boat": ("선상낚시", 15000)}


class NearbyPlaceOut(BaseModel):
    name: str
    kind: Kind
    category: str | None
    phone: str | None
    address: str
    lat: float
    lon: float
    distance_m: int
    kakao_url: str | None


class NearbyOut(BaseModel):
    shops: list[NearbyPlaceOut]
    boats: list[NearbyPlaceOut]
    source: str = "카카오 로컬"
    fetched_at: datetime
    # 검색하지 않은 이유 (좌표 없음·의심). 결과가 비어도 이유가 없으면 「근처에 없음」
    skipped: str | None = None


def _keep(kind: str, category: str) -> bool:
    if "낚시" not in category:
        return False
    if kind == "boat" and category.endswith("낚시터"):
        return False
    return True


def _search(key: str, cache_key: str, lat: float, lon: float, kind: str) -> list[NearbyPlaceOut]:
    hit = _cache.get((cache_key, kind))
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    query, radius = _QUERY[kind]
    try:
        r = httpx.get(
            _URL,
            params={
                "query": query,
                "x": lon,
                "y": lat,
                "radius": radius,
                "sort": "distance",
                "size": 15,
            },
            headers={"Authorization": f"KakaoAK {key}"},
            timeout=5,
        )
        r.raise_for_status()
        docs = r.json().get("documents", [])
    except (httpx.HTTPError, ValueError):
        msg = "근처 낚시점을 불러오지 못했어요. 잠시 후 다시 시도해 주세요"
        raise HTTPException(status_code=502, detail=msg) from None
    out = [
        NearbyPlaceOut(
            name=d.get("place_name") or "",
            kind=kind,  # type: ignore[arg-type]
            category=(d.get("category_name") or "").split(" > ")[-1] or None,
            phone=d.get("phone") or None,
            address=d.get("road_address_name") or d.get("address_name") or "",
            lat=float(d["y"]),
            lon=float(d["x"]),
            distance_m=int(d.get("distance") or 0),
            kakao_url=d.get("place_url") or None,
        )
        for d in docs
        if d.get("x") and d.get("y") and _keep(kind, d.get("category_name") or "")
    ][:8]
    if len(_cache) > 1000:
        _cache.clear()
    _cache[(cache_key, kind)] = (time.monotonic(), out)
    return out


@router.get("/places/{place_id}/nearby", response_model=NearbyOut)
def nearby(place_id: int, db: DbSession):
    place = db.get(Place, place_id)
    if place is None or not place.is_active:
        raise HTTPException(status_code=404, detail="낚시터를 찾을 수 없습니다")
    now = datetime.now(UTC)
    if place.lat is None or place.lon is None or place.id in suspect_place_ids(db):
        why = "위치가 확인되지 않은 낚시터라 근처 검색을 하지 않았어요"
        return NearbyOut(shops=[], boats=[], fetched_at=now, skipped=why)
    return search_around(f"p{place.id}", place.lat, place.lon)


def search_around(cache_key: str, lat: float, lon: float) -> NearbyOut:
    """좌표 주변 낚시점(5km)·낚시배(15km). 낚시터와 갯바위 포인트가 같이 쓴다"""
    key = get_settings().kakao_rest_key
    if not key:
        raise HTTPException(status_code=503, detail="근처 검색을 지금 쓸 수 없어요")
    return NearbyOut(
        shops=_search(key, cache_key, lat, lon, "shop"),
        boats=_search(key, cache_key, lat, lon, "boat"),
        fetched_at=datetime.now(UTC),
    )
