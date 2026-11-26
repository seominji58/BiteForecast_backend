# ruff: noqa: E501  — AI 안내문·도구 설명은 문장 단위로 둔다
"""입질예보에게 묻기 (2026-11-26) — OpenAI Responses API + 우리 자료 조회 도구.

AI 가 바다 상태를 추측하지 않게, 수치·특보·지수·금어기는 반드시 아래 도구로 조회한 값만 말하게 한다.
- 도구: 낚시터 찾기 · 그날 해황 요약 · 어종별 바다낚시지수 · 특보 · 금어기/금지체장
- 답하지 않는 것: 먹어도 되는지·독 · 출조 강행 판단 · 자료에 없는 것 (시스템 안내로 막는다)
- 대화는 서버에 저장하지 않는다. 사용자당 하루 횟수 제한 (fish_id 와 같은 방식, 메모리)
"""

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.timeutil import today_kst
from app.models import Place, PlaceStation, Region
from app.services import warning
from app.services.fish_id import FishIdError, _client  # 같은 OpenAI 연결·오류 형식

log = logging.getLogger(__name__)
URL = "https://api.openai.com/v1/responses"
MAX_ROUNDS = 4
RULES_FILE = Path(__file__).resolve().parent.parent.parent / "seeds" / "fishing_rules.json"

SYSTEM = """당신은 한국 바다낚시 앱 「입질예보」의 도우미입니다. 한국어로, 짧고 친절하게(5문장 이내) 답하세요.
규칙:
1. 파고·바람·수온·물때·특보·바다낚시지수·금어기 같은 사실은 반드시 도구로 조회한 값만 말하세요. 도구에 없으면 「자료가 없어요」라고 하세요. 추측하거나 지어내지 마세요.
2. 수치를 말할 때는 출처(기상청·국립해양조사원 등)와 날짜를 함께 말하세요.
3. 먹어도 되는지, 독이 있는지, 손질·요리법은 답하지 마세요 → 「안전 문제라 답하지 않아요. 모르는 물고기는 먹지 마세요.」
4. 「가도 돼?」처럼 출조 여부를 묻으면 수치와 특보만 알려 주고, 판단은 기상청 특보와 현장 상황으로 하라고 하세요. 「안전하다」고 단정하지 마세요.
5. 낚시 장소를 추천할 때는 공식 바다낚시지수(국립해양조사원) 등급을 근거로 하고, 지수는 조과를 보장하지 않는다고 덧붙이세요.
6. 낚시와 관계없는 질문에는 앱 사용과 바다낚시 질문만 도울 수 있다고 하세요.
오늘(한국 시간)은 {today} 입니다. 조회할 수 있는 날짜는 {first}부터 {last}까지예요."""

TOOLS = [
    {
        "type": "function",
        "name": "search_places",
        "description": "낚시터 이름·지역으로 앱의 낚시터를 찾는다. 해황을 조회하려면 먼저 이걸로 place_id 를 얻는다",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "예: 남애항, 거금도, 여수"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "place_conditions",
        "description": "낚시터 한 곳의 그날 해황 요약: 특보, 파고·바람 예보 최대, 수온, 물때, 만조·간조, 일출·일몰, 바다낚시지수",
        "parameters": {
            "type": "object",
            "properties": {
                "place_id": {"type": "integer"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["place_id", "date"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "fishing_index",
        "description": "국립해양조사원 어종별 바다낚시지수: 그날 그 어종 등급이 좋은 지점 목록",
        "parameters": {
            "type": "object",
            "properties": {
                "species": {"type": "string", "description": "예: 감성돔, 참돔, 우럭(조피볼락)"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["species", "date"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "marine_warnings",
        "description": "기상청 특보 현황(발효 중·예비). area 는 바다나 도 이름(예: 서해, 남해동부, 전남). 빈 문자열이면 전체",
        "parameters": {
            "type": "object",
            "properties": {"area": {"type": "string"}},
            "required": ["area"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "fishing_rules",
        "description": "수산자원관리법 금어기·금지체장 (어종 이름으로)",
        "parameters": {
            "type": "object",
            "properties": {"species": {"type": "string"}},
            "required": ["species"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


# --- 도구 구현 (모두 우리 DB·시드만 읽는다) ---
def _day(s: str) -> date | None:
    try:
        d = date.fromisoformat(s)
    except ValueError:
        return None
    t = today_kst()
    return d if t - timedelta(days=3) <= d <= t + timedelta(days=6) else None


def _v(x) -> float | None:
    return getattr(x, "v", None) if x is not None else None


def tool_search_places(db: Session, query: str) -> dict:
    q = query.strip()
    if not q:
        return {"places": []}
    rows = db.execute(
        select(Place.id, Place.name, Region.name, Place.type)
        .join(Region, Region.id == Place.region_id)
        .where(Place.is_active.is_(True), or_(Place.name.contains(q), Region.name.contains(q)))
        .limit(8)
    ).all()
    return {"places": [{"place_id": i, "name": n, "region": r, "type": str(t)} for i, n, r, t in rows]}


def tool_place_conditions(db: Session, place_id: int, day_s: str) -> dict:
    from app.services.summary import summarize_place

    day = _day(day_s)
    if day is None:
        return {"error": "조회할 수 없는 날짜예요"}
    p = db.scalar(
        select(Place)
        .where(Place.id == place_id, Place.is_active.is_(True))
        .options(
            selectinload(Place.region),
            selectinload(Place.info),
            selectinload(Place.stations).selectinload(PlaceStation.station),
        )
    )
    if p is None:
        return {"error": "낚시터를 찾지 못했어요"}
    s = summarize_place(db, p, day)
    idx = s.index
    return {
        "place": p.name,
        "date": day.isoformat(),
        "warning": {"level": s.warning_level, "types": s.warning_types, "source": "기상청 특보"},
        "wave_forecast_max_m": _v(s.wave_fc_max),
        "wind_forecast_max_ms": _v(s.wind_fc_max),
        "wind_direction": s.wind_dir_fc,
        "water_temp_c": _v(s.temp_obs) or (s.temp_rt.v if s.temp_rt else None),
        "air_temp_min_max": [_v(s.air_temp_fc_min), _v(s.air_temp_fc_max)],
        "rain_chance_max_pct": _v(s.pop_fc_max),
        "mulddae": s.mulddae,
        "tides": [{"type": t.type, "time": t.t.isoformat()} for t in s.tides][:4],
        "sunrise": s.sunrise,
        "sunset": s.sunset,
        "fishing_index": (
            {
                "best": idx.best,
                "worst": idx.worst,
                "period": idx.period,
                "source": "국립해양조사원 바다낚시지수",
            }
            if idx
            else None
        ),
        "sources": "기상청 단기예보·특보, 국립해양조사원 조석·바다낚시지수",
    }


RANK = {"매우좋음": 5, "좋음": 4, "보통": 3, "나쁨": 2, "매우나쁨": 1}


def tool_fishing_index(db: Session, species: str, day_s: str) -> dict:
    from app.services.fishing_index import day_index

    day = _day(day_s)
    if day is None:
        return {"error": "조회할 수 없는 날짜예요"}
    want = re.sub(r"\(.*\)", "", species).strip()
    out = []
    names = {}
    d = day_index(db, day)
    ids = [pl.place_id for pt in d.points for pl in pt.places]
    if ids:
        names = dict(db.execute(select(Place.id, Place.name).where(Place.id.in_(ids))).all())
    for pt in d.points:
        for sp in pt.species:
            if want and want not in sp.species:
                continue
            best = max(sp.grades.values(), key=lambda g: RANK.get(g, 0), default=None)
            if best:
                out.append(
                    {
                        "point": pt.station_name,
                        "species": sp.species,
                        "grades": sp.grades,
                        "best": best,
                        "nearby_places": [
                            {"place_id": pl.place_id, "name": names.get(pl.place_id, "")}
                            for pl in pt.places[:2]
                        ],
                    }
                )
    out.sort(key=lambda x: -RANK.get(x["best"], 0))
    return {
        "date": day.isoformat(),
        "source": "국립해양조사원 바다낚시지수",
        "points": out[:8],
        "total": len(out),
    }


def tool_marine_warnings(db: Session, area: str) -> dict:
    snap = warning.latest_snapshot(db)
    if snap is None:
        return {"error": "특보 자료가 없어요"}
    a = area.strip()
    active = [w for w in json.loads(snap.active_json) if not a or any(a in x for x in w["areas"])]
    pre = [w for w in json.loads(snap.preliminary_json) if not a or any(a in x for x in w["areas"])]
    return {
        "source": "기상청 특보",
        "issued_at": snap.issued_at.isoformat() if snap.issued_at else None,
        "active": [{"type": w["type"], "areas": w["areas"][:8]} for w in active][:10],
        "preliminary": [{"type": w["type"], "when": w.get("when"), "areas": w["areas"][:8]} for w in pre][
            :10
        ],
    }


def tool_fishing_rules(species: str) -> dict:
    r = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    want = re.sub(r"\(.*\)", "", species).strip()
    alias = {n for names in r["app_species"].values() for n in names}
    hits_ban = [b for b in r["ban"] if want and (want in b["name"] or b["name"] in want)]
    hits_size = [s for s in r["size"] if want and (want in s["name"] or s["name"] in want)]
    return {
        "source": r["source"],
        "checked_at": r["checked_at"],
        "bans": [{"name": b["name"], "periods": b["periods"], "note": b.get("note")} for b in hits_ban],
        "sizes": [{"name": s["name"], "limit": s["limit"], "measure": s["measure"]} for s in hits_size],
        "note": r["notice"]
        if (hits_ban or hits_size)
        else f"「{want}」 법정 금어기·금지체장 없음 (목록 {len(alias)}종 기준)",
    }


def run_tool(db: Session, name: str, args: dict, seen_places: dict[int, str]) -> dict:
    try:
        if name == "search_places":
            out = tool_search_places(db, args.get("query", ""))
            for p in out["places"]:
                seen_places[p["place_id"]] = p["name"]
            return out
        if name == "place_conditions":
            out = tool_place_conditions(db, int(args["place_id"]), args["date"])
            if "place" in out:
                seen_places[int(args["place_id"])] = out["place"]
            return out
        if name == "fishing_index":
            return tool_fishing_index(db, args["species"], args["date"])
        if name == "marine_warnings":
            return tool_marine_warnings(db, args.get("area", ""))
        if name == "fishing_rules":
            return tool_fishing_rules(args["species"])
    except Exception:  # 도구 하나가 실패해도 답은 이어서 (그 자료는 「없음」)
        log.exception("ask 도구 실패 %s", name)
        db.rollback()
    return {"error": "자료를 가져오지 못했어요"}


# --- 하루 횟수 ---
@dataclass
class _Quota:
    day: str = ""
    total: int = 0
    per_user: dict[int, int] = field(default_factory=dict)


_quota = _Quota()
_lock = threading.Lock()


def take_quota(user_id: int) -> int:
    s = get_settings()
    with _lock:
        d = today_kst().isoformat()
        if _quota.day != d:
            _quota.day, _quota.total, _quota.per_user = d, 0, {}
        used = _quota.per_user.get(user_id, 0)
        if used >= s.ask_daily_per_user:
            raise FishIdError(
                429, f"오늘은 {s.ask_daily_per_user}번 모두 물어봤어요. 내일 다시 물어봐 주세요"
            )
        if _quota.total >= s.ask_daily_total:
            raise FishIdError(429, "오늘 질문이 많아 잠시 쉬고 있어요. 내일 다시 시도해 주세요")
        _quota.per_user[user_id] = used + 1
        _quota.total += 1
        return s.ask_daily_per_user - used - 1


def give_back(user_id: int) -> None:
    with _lock:
        if _quota.per_user.get(user_id):
            _quota.per_user[user_id] -= 1
            _quota.total = max(0, _quota.total - 1)


def remaining(user_id: int) -> int:
    s = get_settings()
    with _lock:
        if _quota.day != today_kst().isoformat():
            return s.ask_daily_per_user
        return max(0, s.ask_daily_per_user - _quota.per_user.get(user_id, 0))


def ask(db: Session, history: list[dict], place_hint: str | None = None) -> tuple[str, dict[int, str]]:
    """history: [{role: user|assistant, content}] (마지막은 user). (답, 참고한 낚시터) 를 돌려준다"""
    s = get_settings()
    t = today_kst()
    system = SYSTEM.format(
        today=t.isoformat(),
        first=(t - timedelta(days=3)).isoformat(),
        last=(t + timedelta(days=6)).isoformat(),
    )
    if place_hint:
        system += f"\n사용자는 지금 「{place_hint}」 낚시터 화면에서 묻고 있어요."
    items: list[dict] = [{"role": m["role"], "content": m["content"]} for m in history]
    seen: dict[int, str] = {}
    reasoning = s.openai_model.startswith(("gpt-5", "o"))
    with _client() as http:
        for _ in range(MAX_ROUNDS):
            body = {
                "model": s.openai_model,
                "instructions": system,
                "input": items,
                "tools": TOOLS,
                "store": False,
                "max_output_tokens": 3000 if reasoning else 800,
            }
            if reasoning:
                body["reasoning"] = {"effort": "low"}
                body["include"] = ["reasoning.encrypted_content"]
            try:
                res = http.post(URL, json=body, headers={"Authorization": f"Bearer {s.openai_api_key}"})
            except httpx.HTTPError as e:
                raise FishIdError(503, "AI 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요") from e
            if res.status_code != 200:
                log.warning("OpenAI 오류 %s %s", res.status_code, res.text[:300])
                raise FishIdError(503, "AI가 지금 응답하지 않아요. 잠시 후 다시 시도해 주세요")
            out = res.json().get("output", [])
            calls = [o for o in out if o.get("type") == "function_call"]
            if not calls:
                text = "".join(
                    c.get("text", "")
                    for o in out
                    if o.get("type") == "message"
                    for c in (o.get("content") or [])
                    if c.get("type") == "output_text"
                ).strip()
                return text or "답을 만들지 못했어요. 질문을 조금 바꿔 다시 물어봐 주세요.", seen
            items.extend(out)  # 추론·도구 호출 항목을 그대로 다음 요청에
            for c in calls:
                try:
                    args = json.loads(c.get("arguments") or "{}")
                except ValueError:
                    args = {}
                result = run_tool(db, c["name"], args, seen)
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": c["call_id"],
                        "output": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
    return "자료를 여러 번 찾아봤지만 답을 정리하지 못했어요. 질문을 나눠서 물어봐 주세요.", seen
