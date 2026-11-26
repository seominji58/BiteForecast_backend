"""낚시터 실제 사진 (한국관광공사 TourAPI 매칭) — 2026-11-18.

- seeds/tour_photos.json (scripts/match_tour_photos.py 로 생성)을 읽어 준다
- 사진은 관광공사 이미지 주소 그대로
- 공공누리 제3유형: 출처(한국관광공사) 표시 · 변경 금지 → 앱은 자르지 않고 원본 비율로 보여준다
- 매칭된 낚시터만 사진이 있다 (거리 + 이름이 함께 맞는 곳만, 엉뚱한 사진을 붙이지 않음)
"""

import hashlib
import io
import json
from functools import lru_cache
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from PIL import Image, ImageOps
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


# --- 관광공사 사진 줄여 주기 (2026-11-26) ---
# 「관광사진 갤러리」 원본은 장당 1.2MB(1280px) 정도라 폰에서 한참 회색으로 보였다.
# 서버가 한 번 받아 긴 변을 줄인 JPEG 로 디스크(MEDIA_DIR/tour-cache)에 두고 그다음부터는 그대로 준다.
# 내용은 바꾸지 않고 크기만 줄인다 (공공누리 출처 표시는 앱이 그대로 한다)
_ALLOWED_HOST = "tong.visitkorea.or.kr"
_WIDTHS = (400, 1000)
_MAX_SRC = 10 * 1024 * 1024


def _cache_dir() -> Path:
    from app.services.photos import media_root

    d = media_root() / "tour-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/tour-photo", include_in_schema=False)
def tour_photo(u: str, w: int = 1000):
    from urllib.parse import urlparse

    p = urlparse(u)
    if p.scheme not in ("http", "https") or p.hostname != _ALLOWED_HOST:
        raise HTTPException(status_code=400, detail="관광공사 사진 주소만 받을 수 있어요")
    w = min(_WIDTHS, key=lambda x: abs(x - w))
    key = hashlib.sha1(f"{u}|{w}".encode()).hexdigest()
    path = _cache_dir() / f"{key}.jpg"
    if not path.exists():
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as http:
                res = http.get(u.replace("http://", "https://", 1))
            res.raise_for_status()
            if len(res.content) > _MAX_SRC:
                raise ValueError("too big")
            img = Image.open(io.BytesIO(res.content))
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((w, w))
            tmp = path.with_suffix(".tmp")
            img.save(tmp, format="JPEG", quality=82, optimize=True)
            tmp.replace(path)
        except (httpx.HTTPError, OSError, ValueError):
            # 줄이지 못하면 원본 주소로 보낸다 (앱에서 빈 칸이 되지 않게)
            return RedirectResponse(u.replace("http://", "https://", 1), status_code=302)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=2592000"})
