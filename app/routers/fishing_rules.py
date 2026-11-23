"""금어기·금지체장 (수산자원관리법 시행령 별표1·2 요약) — 2026-11-23.

seeds/fishing_rules.json (scripts/build_fishing_rules.py)을 그대로 준다.
오늘 해당 여부는 앱이 날짜로 계산한다.
법령이 바뀌면 앱 업데이트 없이 이 파일만 바꿔 배포하면 된다.
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Response
from pydantic import BaseModel

router = APIRouter(tags=["meta"])
_FILE = Path(__file__).resolve().parent.parent.parent / "seeds" / "fishing_rules.json"


class BanOut(BaseModel):
    name: str
    group: str
    sci: str
    periods: list[dict]
    notice: bool  # 해수부·시도 고시로 실제 기간이 정해짐
    note: str | None = None


class SizeOut(BaseModel):
    name: str
    group: str
    limit: str
    measure: str
    measure_desc: str
    note: str | None = None


class FishingRulesOut(BaseModel):
    source: str
    law_url: str
    checked_at: str
    notice: str
    ban: list[BanOut]
    size: list[SizeOut]
    app_species: dict[str, list[str]]
    female: list[dict] = []
    exemption_note: str | None = None


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(_FILE.read_text(encoding="utf-8"))


@router.get("/meta/fishing-rules", response_model=FishingRulesOut)
def fishing_rules(response: Response):
    # 기기 HTTP 캐시가 법령 갱신을 6시간씩 가리지 않게 (2026-11-23)
    response.headers["Cache-Control"] = "public, max-age=600"
    return _data()


_SEASONS = Path(__file__).resolve().parent.parent.parent / "seeds" / "species_seasons.json"


@lru_cache(maxsize=1)
def _seasons() -> dict:
    return json.loads(_SEASONS.read_text(encoding="utf-8"))


@router.get("/meta/species-seasons")
def species_seasons(response: Response):
    """앱 어종별 산란기 (수산과학원·국내 논문, scripts/build_species_seasons.py). 잡히는 시기가 아니다"""
    # 기기 HTTP 캐시가 법령 갱신을 6시간씩 가리지 않게 (2026-11-23)
    response.headers["Cache-Control"] = "public, max-age=600"
    return _seasons()


_CATCH = Path(__file__).resolve().parent.parent.parent / "seeds" / "catch_seasons.json"


@lru_cache(maxsize=1)
def _catch() -> dict:
    return json.loads(_CATCH.read_text(encoding="utf-8"))


@router.get("/meta/catch-seasons")
def catch_seasons(response: Response):
    """어종별 바다별 「어획 많은 달」 (통계청 어업생산동향조사). 낚시 조과가 아니다"""
    response.headers["Cache-Control"] = "public, max-age=600"
    return _catch()
