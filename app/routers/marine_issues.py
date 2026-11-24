"""해양 이슈 (2026-11-24): 국립수산과학원 적조 속보·해파리 주간보고 — 원문 요약 그대로, 판정 없음.

화면: 낚시터 상세 「안전 정보」 시트. 최근 14일 적조 속보가 없으면 빈 목록.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.services import nifs_live

router = APIRouter(tags=["meta"])
KST = timezone(timedelta(hours=9))


class RedTideOut(BaseModel):
    date: str
    seas: str | None
    breaking: str | None  # 특보상황 원문
    progress: str | None  # 진행상황
    biology: str | None


class JellyOut(BaseModel):
    title: str
    date: str
    breaking: bool  # 속보(true) / 주간보고(false)


class MarineIssuesOut(BaseModel):
    redtide: list[RedTideOut]
    jelly: list[JellyOut]
    source: str = "국립수산과학원"


def _txt(v) -> str | None:
    s = (str(v).strip() if v is not None else "") or None
    return s[:400] if s else None


@router.get("/meta/marine-issues", response_model=MarineIssuesOut)
def marine_issues(response: Response):
    live = nifs_live.live()
    today = datetime.now(KST).date()
    red = [
        RedTideOut(
            date=r["_date"].isoformat(),
            seas=_txt(r.get("txt_seas")),
            breaking=_txt(r.get("txt_breaking")),
            progress=_txt(r.get("txt_progress")),
            biology=_txt(r.get("nam_biology")),
        )
        for r in nifs_live.recent_redtide(live.redtide, today)[:3]
    ]
    jelly = [
        JellyOut(
            title=_txt(j.get("board_subject")) or "해파리 정보",
            date=str(j.get("inpt_date", "")),
            breaking=j.get("gbn") == "1",
        )
        for j in sorted(live.jelly, key=lambda x: str(x.get("inpt_date", "")), reverse=True)[:2]
    ]
    response.headers["Cache-Control"] = "public, max-age=600"
    return MarineIssuesOut(redtide=red, jelly=jelly)
