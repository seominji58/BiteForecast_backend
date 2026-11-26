"""사진으로 어종 찾기 (2026-11-26, OpenAI Responses API).

- 사진은 서버에서 줄이고(긴 변 1024px) 위치·촬영 정보(EXIF)를 지운 뒤 보낸다. 서버에 저장하지 않는다
- 우리 어종 목록(code·이름)을 같이 보내 그 안에서 고르게 한다 → 앱의 금어기·금지체장 안내와 바로 이어진다
- 답은 후보 최대 3개 + 「얼마나 확실한지」. 확정하지 않는다 (최종 선택은 사용자)
- 먹어도 되는지·독 여부는 답하지 않는다 (틀리면 위험) — 앱에서 고정 문구로 안내
- 비용 보호: 사용자당·서버 전체 하루 횟수 제한 (메모리, 한국 시간 날짜 기준)
"""

import base64
import io
import json
import logging
import re
import threading
from dataclasses import dataclass, field

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings
from app.core.timeutil import today_kst

log = logging.getLogger(__name__)

URL = "https://api.openai.com/v1/responses"
MAX_SIDE = 1024
MAX_BYTES = 10 * 1024 * 1024


class FishIdError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def enabled() -> bool:
    return bool(get_settings().openai_api_key.strip())


# --- 하루 횟수 제한 ---
@dataclass
class _Quota:
    day: str = ""
    total: int = 0
    per_user: dict[int, int] = field(default_factory=dict)


_quota = _Quota()
_lock = threading.Lock()


def take_quota(user_id: int) -> int:
    """한 번 쓴다. 남은 횟수를 돌려주고, 다 썼으면 FishIdError(429)"""
    s = get_settings()
    with _lock:
        day = today_kst().isoformat()
        if _quota.day != day:
            _quota.day, _quota.total, _quota.per_user = day, 0, {}
        used = _quota.per_user.get(user_id, 0)
        if used >= s.fish_id_daily_per_user:
            raise FishIdError(429, f"오늘은 {s.fish_id_daily_per_user}번 모두 썼어요. 내일 다시 쓸 수 있어요")
        if _quota.total >= s.fish_id_daily_total:
            raise FishIdError(429, "오늘 사용량이 많아 잠시 쉬고 있어요. 내일 다시 시도해 주세요")
        _quota.per_user[user_id] = used + 1
        _quota.total += 1
        return s.fish_id_daily_per_user - used - 1


def give_back(user_id: int) -> None:
    """AI 호출이 실패하면 횟수를 돌려준다"""
    with _lock:
        if _quota.per_user.get(user_id):
            _quota.per_user[user_id] -= 1
            _quota.total = max(0, _quota.total - 1)


def remaining(user_id: int) -> int:
    s = get_settings()
    with _lock:
        if _quota.day != today_kst().isoformat():
            return s.fish_id_daily_per_user
        return max(0, s.fish_id_daily_per_user - _quota.per_user.get(user_id, 0))


# --- 사진 준비 ---
def prepare_image(raw: bytes) -> bytes:
    """방향 반영 → RGB → 긴 변 1024 → EXIF 없는 JPEG"""
    if len(raw) > MAX_BYTES:
        raise FishIdError(413, "사진이 너무 커요 (10MB 이하)")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise FishIdError(400, "사진 파일을 읽을 수 없어요 (JPEG·PNG·WEBP)") from None
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


# --- AI 호출 ---
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_fish", "candidates", "photo_tip"],
    "properties": {
        "is_fish": {
            "type": "boolean",
            "description": "사진에 물고기·두족류·갑각류 등 낚시로 잡는 생물이 보이면 true",
        },
        "candidates": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "name", "confidence", "features"],
                "properties": {
                    "code": {
                        "type": ["string", "null"],
                        "description": "목록에 있는 어종이면 그 code, 없으면 null",
                    },
                    "name": {
                        "type": "string",
                        "description": "한국어 표준 이름 (흔히 부르는 이름이 다르면 괄호)",
                    },
                    "confidence": {"type": "string", "enum": ["높음", "보통", "낮음"]},
                    "features": {
                        "type": "string",
                        "description": "사진에서 보이는 구별 특징 한두 개, 40자 이내",
                    },
                },
            },
        },
        "photo_tip": {
            "type": ["string", "null"],
            "description": "판별이 어려우면 어떻게 다시 찍으면 좋은지 한 문장, 아니면 null",
        },
    },
}


def _prompt(species: list[tuple[str, str]]) -> str:
    """우리 목록에서 고르게 하면 민물고기도 바다 어종으로 끼워 맞췄다 (2026-11-26 납지리 → 숭어·참돔).
    → 목록은 「흔한 어종」 참고로만 주고, 이름을 자유롭게 말하게 한 뒤 서버가 이름으로 목록과 맞춘다 (match_code)"""
    common = ", ".join(_base(n) for _, n in species)
    return (
        "당신은 한국 낚시 어종 판별 도우미입니다. 사진 속 생물의 후보를 최대 3개, 가능성 높은 순으로 고르세요.\n"
        "- 먼저 바다고기인지 민물고기인지 몸 모양·비늘·지느러미·수염·입 위치로 판단하세요.\n"
        "- name 에는 한국에서 쓰는 표준 이름을 적고, 민물고기면 이름 뒤에 '(민물)'을 붙이세요. code 는 항상 null 로 두세요.\n"
        f"- 참고로 한국 바다낚시에서 흔한 어종은 {common} 등이에요. 이 중 하나로 보이면 그 이름을 쓰되, 아니면 억지로 맞추지 마세요.\n"
        "- 닮은 어종 구별: 우럭(조피볼락: 머리가 크고 몸이 두툼, 짙은 회갈색, 눈 뒤로 검은 줄) vs 농어(몸이 길고 은백색) vs 볼락(작고 눈이 큼). "
        "붕어(몸이 두툼, 비늘이 큼) vs 납자루·납지리류(작고 납작·높은 몸, 옆면이 반짝임) vs 잉어(입수염 2쌍). "
        "광어(눈이 왼쪽) vs 가자미·도다리(눈이 오른쪽). 감성돔(검은 회색) vs 참돔(붉은색). "
        "복어류(둥근 몸, 비늘 없음, 작은 입·이빨판) vs 쥐치(납작, 등에 가시 하나).\n"
        "- 확실하지 않으면 confidence 를 낮추고 닮은 어종을 함께 후보로 넣으세요. 지어내지 마세요.\n"
        "- 먹어도 되는지·독·요리법은 언급하지 마세요. 물고기 등이 보이지 않으면 is_fish=false."
    )


def _base(name: str) -> str:
    """「우럭(조피볼락)」 → 「우럭」, 「붕어 (민물)」 → 「붕어」"""
    return re.sub(r"\s*\(.*?\)\s*", "", name).strip()


def match_code(name: str, species: list[tuple[str, str]]) -> tuple[str | None, str | None]:
    """AI 가 말한 이름을 우리 목록 어종과 맞춘다 (이름·괄호 속 다른 이름). 민물이면 맞추지 않는다. (code, 목록 이름)"""
    if "민물" in name:
        return None, None
    want = {_base(name), *re.findall(r"\((.*?)\)", name)}
    for code, n in species:
        names = {_base(n), *re.findall(r"\((.*?)\)", n)}
        if want & names:
            return code, n
    return None, None


def _client() -> httpx.Client:
    return httpx.Client(timeout=40)


def identify(jpeg: bytes, species: list[tuple[str, str]], http: httpx.Client | None = None) -> dict:
    s = get_settings()
    body = {
        "model": s.openai_model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": _prompt(species)},
                    {
                        "type": "input_image",
                        "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
                        "detail": "high",
                    },
                ],
            }
        ],
        "text": {"format": {"type": "json_schema", "name": "fish_id", "schema": SCHEMA, "strict": True}},
        "max_output_tokens": 600,
        # 응답을 OpenAI 쪽에 저장하지 않는다 (기본값은 저장)
        "store": False,
    }
    if s.openai_model.startswith(("gpt-5", "o")):
        # 추론 모델: 생각에 쓰는 토큰도 출력 한도에 들어간다 → 짧게 생각하고 한도를 넉넉히
        body["reasoning"] = {"effort": "low"}
        body["max_output_tokens"] = 3000
    own = http is None
    http = http or _client()
    try:
        res = http.post(URL, json=body, headers={"Authorization": f"Bearer {s.openai_api_key}"})
    except httpx.HTTPError as e:
        raise FishIdError(503, "AI 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요") from e
    finally:
        if own:
            http.close()
    if res.status_code != 200:
        log.warning("OpenAI 오류 %s %s", res.status_code, res.text[:200])
        raise FishIdError(503, "AI가 지금 응답하지 않아요. 잠시 후 다시 시도해 주세요")
    data = res.json()
    text = data.get("output_text") or next(
        (
            c.get("text")
            for o in data.get("output", [])
            for c in (o.get("content") or [])
            if c.get("type") == "output_text"
        ),
        None,
    )
    try:
        out = json.loads(text or "")
    except ValueError:
        raise FishIdError(503, "AI 답을 읽지 못했어요. 다시 시도해 주세요") from None
    # 이름으로 우리 목록과 맞춘다. AI 가 낸 code 는 쓰지 않는다 (지어낸 code 로 저장되지 않게)
    for c in out.get("candidates", []):
        code, listed = match_code(c.get("name", ""), species)
        c["code"] = code
        if listed:
            c["name"] = listed
    return out
