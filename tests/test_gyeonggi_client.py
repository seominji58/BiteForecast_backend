"""경기데이터드림 공통 호출: 정상·자료 없음·오류·키 없음·키 가림 (실제 호출 없음)"""

import httpx
import pytest

from app.clients.gyeonggi import GyeonggiClient, GyeonggiError

KEY = "test-gg-key-123456"
SVC = "TestSvc"


def _client(handler):
    return GyeonggiClient(api_key=KEY, http=httpx.Client(transport=httpx.MockTransport(handler)))


def _ok(total, rows):
    return {
        SVC: [
            {"head": [{"list_total_count": total}, {"RESULT": {"CODE": "INFO-000", "MESSAGE": "정상"}}]},
            {"row": rows},
        ]
    }


def test_pages_until_total():
    seen = []

    def h(req):
        seen.append(dict(req.url.params))
        p = int(req.url.params["pIndex"])
        return httpx.Response(200, json=_ok(3, [{"n": p}] * (2 if p == 1 else 1)))

    c = _client(h)
    c_rows = c.all(SVC, SIGUN_NM="화성시")
    assert len(c_rows) == 3
    assert seen[0]["KEY"] == KEY and seen[0]["Type"] == "json" and seen[0]["SIGUN_NM"] == "화성시"
    assert seen[0]["pSize"] == "1000"


def test_no_data_is_empty_not_zero():
    c = _client(
        lambda req: httpx.Response(
            200, json={"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}
        )
    )
    assert c.all(SVC) == []


def test_error_codes_and_key_hidden():
    c = _client(lambda req: httpx.Response(200, json={"RESULT": {"CODE": "ERROR-310", "MESSAGE": "x"}}))
    with pytest.raises(GyeonggiError) as e:
        c.all(SVC)
    assert e.value.code == "ERROR-310"
    c2 = _client(
        lambda req: httpx.Response(200, json={"RESULT": {"CODE": "ERROR-999", "MESSAGE": f"bad {KEY}"}})
    )
    with pytest.raises(GyeonggiError) as e2:
        c2.all(SVC)
    assert KEY not in str(e2.value)


def test_http_and_network_failures():
    with pytest.raises(GyeonggiError) as e:
        _client(lambda req: httpx.Response(500, text="err")).all(SVC)
    assert e.value.code == "HTTP_500"

    def boom(req):
        raise httpx.ConnectError("down")

    with pytest.raises(GyeonggiError) as e2:
        _client(boom).all(SVC)
    assert e2.value.code == "NETWORK"


def test_missing_key(monkeypatch):
    with pytest.raises(GyeonggiError) as e:
        GyeonggiClient(api_key="")
    assert e.value.code == "NO_KEY"


def test_logsafe_hides_gg_key(monkeypatch):
    from app.core import logsafe

    assert (
        logsafe.redact(f"https://openapi.gg.go.kr/X?KEY={KEY}&Type=json")
        == "https://openapi.gg.go.kr/X?KEY=***&Type=json"
    )
