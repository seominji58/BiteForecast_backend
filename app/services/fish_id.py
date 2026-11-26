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
    listing = ", ".join(f"{code}={name}" for code, name in species)
    return (
        "당신은 한국 바다낚시 어종 판별을 돕는 도우미입니다.\n"
        "사진 속 생물이 무엇인지 후보를 최대 3개 고르세요.\n"
        "- 가능하면 아래 목록에서 고르고 code 를 적으세요.\n"
        "- 목록에 없으면 code 는 null, name 에 한국어 이름을 적으세요.\n"
        "- 가장 가능성 높은 후보부터. 확실하지 않으면 confidence 를 낮추세요. 지어내지 마세요.\n"
        "- 넙치류는 배를 아래로 두고 볼 때 두 눈이 왼쪽이면 광어(넙치), 오른쪽이면 가자미·도다리(좌광우도).\n"
        "  광어는 입이 크고 이빨이 날카로우며, 가자미·도다리는 입이 작다. 이 특징을 먼저 확인하세요.\n"
        "- 먹어도 되는지, 독이 있는지, 요리법은 절대 언급하지 마세요.\n"
        "- 물고기 등이 보이지 않으면 is_fish=false, candidates 는 빈 배열.\n"
        f"어종 목록: {listing}"
    )


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
    # 목록에 없는 code 는 지운다 (AI 가 만들어 낸 code 로 어종을 저장하지 않게)
    valid = {code: name for code, name in species}
    for c in out.get("candidates", []):
        if c.get("code") not in valid:
            c["code"] = None
        else:
            c["name"] = valid[c["code"]]
    return out
