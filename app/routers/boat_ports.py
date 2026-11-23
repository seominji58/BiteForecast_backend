"""낚시어선 출항항 (해양수산부 낚시 어선업 신고정보 → scripts/build_boat_ports.py) — 2026-11-23.

- GET /boat-ports: 출항항 목록 (위치·영업 중 낚시어선 수·최대 승객 수·배 이름 일부)
- GET /boat-ports/{id}/nearby: 그 항구 주변 카카오 선상낚시 업체 (전화 연결용. 신고정보에는 연락처가 없다)
- id 는 자료 파일 안 순서(척수 많은 순)로 매긴다. 파일을 다시 만들면 바뀔 수 있어 앱은 저장하지 않는다
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.routers.nearby import NearbyOut, search_around

router = APIRouter(tags=["places"])
_FILE = Path(__file__).resolve().parent.parent.parent / "seeds" / "fishing_boat_ports.json"


class BoatPortOut(BaseModel):
    id: int
    name: str
    sgg: str
    lat: float
    lon: float
    kakao_name: str
    kakao_url: str | None = None
    boats: int
    max_passengers: int
    boat_names: list[str] = []


class BoatPortsOut(BaseModel):
    source: str
    as_of: str
    boats_total: int
    boats_on_map: int
    notice: str
    ports: list[BoatPortOut]


@lru_cache(maxsize=1)
def _data() -> dict:
    d = json.loads(_FILE.read_text(encoding="utf-8"))
    ports = [{**p, "id": i + 1} for i, p in enumerate(d["ports"])]
    return {
        "source": d["source"],
        "as_of": d["as_of"],
        "boats_total": d["boats_total"],
        "boats_on_map": d["boats_on_map"],
        "notice": "신고된 낚시어선 수예요. 연락처·출항 시간은 자료에 없어 업체에 직접 확인하세요. "
        "항구 위치는 카카오 기준이라 실제 출항 선착장과 다를 수 있어요.",
        "ports": ports,
    }


@router.get("/boat-ports", response_model=BoatPortsOut)
def boat_ports(response: Response):
    response.headers["Cache-Control"] = "public, max-age=3600"
    return _data()


@router.get("/boat-ports/{port_id}/nearby", response_model=NearbyOut)
def boat_port_nearby(port_id: int):
    p = next((p for p in _data()["ports"] if p["id"] == port_id), None)
    if p is None:
        raise HTTPException(status_code=404, detail="항구를 찾을 수 없습니다")
    return search_around(f"h{port_id}", p["lat"], p["lon"])
