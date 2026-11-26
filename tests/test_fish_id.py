"""사진으로 어종 찾기: 로그인·키 없으면 꺼짐·횟수 제한·목록 밖 code 제거·사진 EXIF 제거 (AI 호출은 가짜)"""

import io
import json

import httpx
import pytest
from PIL import Image

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Species
from app.services import fish_id as svc
from tests.conftest import make_jpeg

URL = "/api/v1/fish-id"


def _file(data: bytes | None = None):
    return {"file": ("a.jpg", data or make_jpeg(gps=True, size=(2000, 1500)), "image/jpeg")}


@pytest.fixture()
def on(monkeypatch):
    """키가 있는 것처럼 + AI 응답을 가짜로. 보낸 요청을 sent 에 담는다"""
    s = get_settings()
    monkeypatch.setattr(s, "openai_api_key", "test-key")
    monkeypatch.setattr(s, "fish_id_daily_per_user", 2)
    monkeypatch.setattr(svc, "_quota", svc._Quota())
    with SessionLocal() as db:
        if not db.get(Species, "black_porgy"):
            db.add(Species(code="black_porgy", name_ko="감성돔"))
            db.commit()
    sent = []
    answer = {
        "is_fish": True,
        "candidates": [
            {
                "code": "black_porgy",
                "name": "감성돔?",
                "confidence": "높음",
                "features": "은회색 몸통, 검은 가로줄",
            },
            {"code": "made_up_code", "name": "참돔", "confidence": "낮음", "features": "붉은 몸"},
        ],
        "photo_tip": None,
    }

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content))
        assert req.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200, json={"output": [{"content": [{"type": "output_text", "text": json.dumps(answer)}]}]}
        )

    monkeypatch.setattr(svc, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return sent


def test_requires_login_and_key(client, device):
    assert client.post(URL, files=_file()).status_code == 401
    r = client.post(URL, files=_file(), headers=device)  # 테스트 환경엔 키 없음
    assert r.status_code == 503
    assert client.get(f"{URL}/status", headers=device).json()["enabled"] is False


def test_identify_maps_codes_and_strips_exif(client, device, on):
    r = client.post(URL, files=_file(), headers=device)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_fish"] is True
    c1, c2 = body["candidates"]
    assert c1["code"] == "black_porgy" and c1["name"] == "감성돔"  # 이름은 우리 목록 값
    assert c2["code"] is None and c2["name"] == "참돔"  # 목록에 없는 code 는 지움
    assert "먹어도" in body["notice"] and body["remaining"] == 1

    # 보낸 사진: 1024px 이하, EXIF(위치) 없음 · 어종 목록 포함
    content = on[0]["input"][0]["content"]
    assert "black_porgy=감성돔" in content[0]["text"]
    import base64

    img = Image.open(io.BytesIO(base64.b64decode(content[1]["image_url"].split(",", 1)[1])))
    assert max(img.size) <= 1024 and not img.getexif()


def test_daily_limit(client, device, on):
    assert client.post(URL, files=_file(), headers=device).status_code == 200
    assert client.post(URL, files=_file(), headers=device).status_code == 200
    r = client.post(URL, files=_file(), headers=device)
    assert r.status_code == 429 and "내일" in r.json()["error"]["message"]
    assert client.get(f"{URL}/status", headers=device).json()["remaining"] == 0


def test_bad_image_does_not_use_quota(client, device, on):
    assert client.post(URL, files=_file(b"not an image"), headers=device).status_code == 400
    assert client.get(f"{URL}/status", headers=device).json()["remaining"] == 2


def test_ai_failure_gives_quota_back(client, device, on, monkeypatch):
    boom = httpx.MockTransport(lambda req: httpx.Response(500, text="boom"))
    monkeypatch.setattr(svc, "_client", lambda: httpx.Client(transport=boom))
    assert client.post(URL, files=_file(), headers=device).status_code == 503
    assert client.get(f"{URL}/status", headers=device).json()["remaining"] == 2
