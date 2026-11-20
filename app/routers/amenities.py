"""낚시터·갯바위 포인트 주변 편의시설: 편의점·주차장·공중화장실 (카카오 로컬, 2026-11-20).

- 편의점(CS2)·주차장(PK6): 카카오 분류(카테고리) 검색
- 화장실: 카카오에 화장실 분류 코드가 없어 「공중화장실」 키워드 검색 후 분류에 「화장실」이 있는 것만
- 반경 2km, 가까운 순 3곳씩. 결과가 없으면 비워 둔다 (가짜로 채우지 않음)
- 위치가 의심스러운 낚시터는 거리가 틀릴 수 있어 검색하지 않는다 (근처 낚시점과 같은 기준)
- 카카오 REST 키는 서버에만. 메모리 캐시 6시간 (편의시설은 자주 바뀌지 않음)
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import DbSession
from app.core.config import get_settings
from app.models.place import Place
from app.routers import rock_points
from app.services.location import suspect_place_ids

router = APIRouter(tags=["places"])
_BASE = "https://dapi.kakao.com/v2/local/search"
RADIUS = 2000
PER_KIND = 3
_TTL = 6 * 3600
_cache: dict[str, tuple[float, "AmenitiesOut"]] = {}


class AmenityOut(BaseModel):
    name: str
    address: str
    phone: str | None
    lat: float
    lon: float
    distance_m: int
    kakao_url: str | None


class AmenitiesOut(BaseModel):
    stores: list[AmenityOut]
    parking: list[AmenityOut]
    toilets: list[AmenityOut]
    radius_m: int = RADIUS
    source: str = "카카오 로컬"
    fetched_at: datetime
    skipped: str | None = None


def _get(key: str, path: str, params: dict) -> list[dict]:
    r = httpx.get(
        f"{_BASE}/{path}.json",
        params={**params, "radius": RADIUS, "sort": "distance", "size": 15},
        headers={"Authorization": f"KakaoAK {key}"},
        timeout=5,
    )
    r.raise_for_status()
    return r.json().get("documents", [])


def _out(docs: list[dict], keep=lambda d: True) -> list[AmenityOut]:
    return [
        AmenityOut(
            name=d.get("place_name") or "",
            address=d.get("road_address_name") or d.get("address_name") or "",
            phone=d.get("phone") or None,
            lat=float(d["y"]),
            lon=float(d["x"]),
            distance_m=int(d.get("distance") or 0),
            kakao_url=d.get("place_url") or None,
        )
        for d in docs
        if d.get("x") and d.get("y") and keep(d)
    ][:PER_KIND]


def amenities_around(cache_key: str, lat: float, lon: float) -> AmenitiesOut:
    hit = _cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    key = get_settings().kakao_rest_key
    if not key:
        raise HTTPException(status_code=503, detail="주변 편의시설 검색을 지금 쓸 수 없어요")
    xy = {"x": lon, "y": lat}
    jobs = {
        "stores": ("category", {**xy, "category_group_code": "CS2"}),
        "parking": ("category", {**xy, "category_group_code": "PK6"}),
        "toilets": ("keyword", {**xy, "query": "공중화장실"}),
    }
    try:
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {k: ex.submit(_get, key, path, p) for k, (path, p) in jobs.items()}
            docs = {k: f.result() for k, f in futs.items()}
    except (httpx.HTTPError, ValueError):
        raise HTTPException(
            status_code=502, detail="주변 편의시설을 불러오지 못했어요. 잠시 후 다시 시도해 주세요"
        ) from None
    out = AmenitiesOut(
        stores=_out(docs["stores"]),
        parking=_out(docs["parking"]),
        toilets=_out(docs["toilets"], lambda d: "화장실" in (d.get("category_name") or "")),
        fetched_at=datetime.now(UTC),
    )
    if len(_cache) > 2000:
        _cache.clear()
    _cache[cache_key] = (time.monotonic(), out)
    return out


@router.get("/places/{place_id}/amenities", response_model=AmenitiesOut)
def place_amenities(place_id: int, db: DbSession):
    place = db.get(Place, place_id)
    if place is None or not place.is_active:
        raise HTTPException(status_code=404, detail="낚시터를 찾을 수 없습니다")
    if place.lat is None or place.lon is None or place.id in suspect_place_ids(db):
        why = "위치가 확인되지 않은 낚시터라 주변 검색을 하지 않았어요"
        return AmenitiesOut(stores=[], parking=[], toilets=[], fetched_at=datetime.now(UTC), skipped=why)
    return amenities_around(f"p{place.id}", place.lat, place.lon)


@router.get("/rock-points/{point_id}/amenities", response_model=AmenitiesOut)
def rock_amenities(point_id: int):
    p = next((p for p in rock_points._data()["points"] if p["id"] == point_id), None)
    if p is None:
        raise HTTPException(status_code=404, detail="포인트를 찾을 수 없습니다")
    return amenities_around(f"r{point_id}", p["lat"], p["lon"])
