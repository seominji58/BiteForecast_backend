"""낚시터 공공데이터 안내 (2026-11-26) — 국립공원·국가어항·해변·시군 낚시통제구역.

seeds/place_notices.json (scripts/build_place_notices.py 로 생성)을 읽어 준다.
판정이 아니라 공식 자료 안내다 — 「낚시 가능·불가」로 쓰지 않는다.
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["places"])
_FILE = Path(__file__).resolve().parent.parent.parent / "seeds" / "place_notices.json"


class ZoneItemOut(BaseModel):
    name: str
    area: str | None = None
    since: str | None = None
    rule: str | None = None


class NoticeOut(BaseModel):
    kind: str  # park | harbor | beach | zone
    title: str
    detail: str
    source_name: str | None = None
    source_url: str | None = None
    source_date: str | None = None
    zone_items: list[ZoneItemOut] = []


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"places": {}, "sources": {}, "zones": {}}


@router.get("/places/{place_id}/notices", response_model=list[NoticeOut])
def place_notices(place_id: int):
    d = _data()
    out = []
    for n in d.get("places", {}).get(str(place_id), []):
        src = d.get("sources", {}).get(n.get("source") or "", {})
        item = NoticeOut(
            kind=n["kind"],
            title=n["title"],
            detail=n["detail"],
            source_name=src.get("name"),
            source_url=src.get("url"),
            source_date=src.get("date"),
        )
        if n["kind"] == "zone":
            z = d.get("zones", {}).get(n.get("region"), {})
            item.source_name, item.source_url, item.source_date = z.get("source"), z.get("url"), z.get("date")
            item.zone_items = [ZoneItemOut(**i) for i in z.get("items", [])]
        out.append(item)
    return out
