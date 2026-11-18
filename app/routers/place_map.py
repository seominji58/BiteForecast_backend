"""낚시터 위성 사진 (네이버 클라우드 Static Map 대행) — 2026-11-18.

- 사진 자료가 없는 낚시터를 글자만이 아니라 실제 위치 모습(방파제·갯바위·해안선)으로 보여주기 위해
- 네이버 클라우드 키는 서버에만 둔다. 앱은 이 주소의 이미지만 받는다
- 좌표가 없거나 의심(D등급)인 낚시터는 엉뚱한 곳이 보이므로 404 (앱은 기본 그림을 쓴다)
- 바다 위 지수 지점(선상·섬 단위)은 위성으로 확대하면 물만 보여서, 멀리서 본 위성+지명(hybrid)으로
- 같은 낚시터·크기는 서버 메모리에 1시간, 앱(기기)에는 하루 캐시
"""

import time
from collections import OrderedDict
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import DbSession
from app.core.config import get_settings
from app.models.place import Place
from app.services.location import suspect_place_ids

router = APIRouter(tags=["places"])
_URL = "https://maps.apigw.ntruss.com/map-static/v2/raster"
_TTL = 3600
_MAX = 300
_cache: OrderedDict[tuple[int, str], tuple[float, bytes]] = OrderedDict()

# 크기별 (가로, 세로) — scale=2 로 받아 선명하게
_SIZE: dict[str, tuple[int, int]] = {"hero": (640, 320), "thumb": (160, 160)}


def _params(place: Place, size: str) -> dict:
    w, h = _SIZE[size]
    sea = getattr(place.type, "value", place.type) in ("boat", "point")
    return {
        "w": w,
        "h": h,
        "scale": 2,
        "center": f"{place.lon},{place.lat}",
        "level": 10 if sea else 15,
        "maptype": "satellite",
        "markers": f"type:d|size:mid|pos:{place.lon} {place.lat}|color:0xF97316",
        "format": "jpg",
    }


@router.get("/places/{place_id}/map.jpg")
def place_map(place_id: int, db: DbSession, size: Literal["hero", "thumb"] = Query("hero")):
    place = db.get(Place, place_id)
    if place is None or not place.is_active:
        raise HTTPException(status_code=404, detail="낚시터를 찾을 수 없습니다")
    if place.lat is None or place.lon is None or place.id in suspect_place_ids(db):
        raise HTTPException(status_code=404, detail="위치가 확인되지 않은 낚시터예요")
    s = get_settings()
    if not s.ncp_map_client_id or not s.ncp_map_client_secret:
        raise HTTPException(status_code=503, detail="위성 사진을 지금 쓸 수 없어요")
    key = (place.id, size)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _TTL:
        _cache.move_to_end(key)
        body = hit[1]
    else:
        try:
            r = httpx.get(
                _URL,
                params=_params(place, size),
                headers={
                    "X-NCP-APIGW-API-KEY-ID": s.ncp_map_client_id,
                    "X-NCP-APIGW-API-KEY": s.ncp_map_client_secret,
                },
                timeout=8,
            )
            r.raise_for_status()
            if not r.headers.get("content-type", "").startswith("image/"):
                raise ValueError("not an image")
            body = r.content
        except (httpx.HTTPError, ValueError):
            raise HTTPException(status_code=502, detail="위성 사진을 불러오지 못했어요") from None
        _cache[key] = (time.monotonic(), body)
        while len(_cache) > _MAX:
            _cache.popitem(last=False)
    return Response(content=body, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
