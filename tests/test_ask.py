"""입질예보에게 묻기: 도구 호출 흐름(가짜 AI) · 금어기 도구 · 로그인·키·횟수 · 마지막은 질문"""

import json

import httpx
import pytest

from app.core.config import get_settings
from app.services import ask as svc
from app.services import fish_id

URL = "/api/v1/ask"


@pytest.fixture()
def ai(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "openai_api_key", "test-key")
    monkeypatch.setattr(s, "ask_enabled", True)
    monkeypatch.setattr(s, "ask_daily_per_user", 2)
    monkeypatch.setattr(svc, "_quota", svc._Quota())
    sent = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        sent.append(body)
        outs = [i for i in body["input"] if i.get("type") == "function_call_output"]
        if not outs:  # 1번째: 도구 호출
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "function_call",
                            "name": "fishing_rules",
                            "arguments": json.dumps({"species": "감성돔"}),
                            "call_id": "c1",
                        }
                    ]
                },
            )
        data = json.loads(outs[0]["output"])
        text = f"감성돔 금지체장은 {data['sizes'][0]['limit']}예요 (수산자원관리법)."
        return httpx.Response(
            200, json={"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}
        )

    monkeypatch.setattr(fish_id, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(svc, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return sent


def test_requires_login_and_key(client, device):
    q = {"messages": [{"role": "user", "content": "감성돔 금어기?"}]}
    assert client.post(URL, json=q).status_code == 401
    assert client.post(URL, json=q, headers=device).status_code == 503


def test_tool_loop_uses_our_data(client, device, ai):
    q = {"messages": [{"role": "user", "content": "감성돔 몇 cm부터 잡아도 돼?"}]}
    r = client.post(URL, json=q, headers=device)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "25cm" in body["answer"] and body["remaining"] == 1
    # 두 번째 요청에 도구 결과를 붙여 보냈고, 저장은 끔
    assert len(ai) == 2 and ai[0]["store"] is False and ai[0]["tools"]
    assert "먹어도" in ai[0]["instructions"]


def test_quota_and_last_must_be_user(client, device, ai):
    q = {"messages": [{"role": "user", "content": "감성돔?"}]}
    assert client.post(URL, json=q, headers=device).status_code == 200
    assert client.post(URL, json=q, headers=device).status_code == 200
    assert client.post(URL, json=q, headers=device).status_code == 429
    bad = {"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]}
    assert client.post(URL, json=bad, headers=device).status_code == 400


def test_rules_tool_no_rule_species():
    out = svc.tool_fishing_rules("전갱이")
    assert not out["bans"] and not out["sizes"] and "없음" in out["note"]


def test_off_by_default(client, device, monkeypatch):
    """OpenAI 키가 있어도 ask_enabled 가 꺼져 있으면 쓰지 않는다 (어종 찾기만 OpenAI)"""
    monkeypatch.setattr(get_settings(), "openai_api_key", "test-key")
    assert client.get(f"{URL}/status", headers=device).json()["enabled"] is False
    q = {"messages": [{"role": "user", "content": "a"}]}
    assert client.post(URL, json=q, headers=device).status_code == 503
