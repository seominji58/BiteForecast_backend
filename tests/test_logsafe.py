"""로그에 인증키가 남지 않는지"""

import logging

from app.core import logsafe


def test_redact_known_and_query_keys(monkeypatch):
    s = logsafe.get_settings()
    monkeypatch.setattr(s, "data_go_kr_api_key", "SECRETKEY1234567890")
    text = "GET https://apis.data.go.kr/x?serviceKey=OLDKEY999&pageNo=1 실패: SECRETKEY1234567890"
    out = logsafe.redact(text)
    assert "SECRETKEY1234567890" not in out and "OLDKEY999" not in out
    assert "serviceKey=***" in out


def test_filter_applies_to_log_records(monkeypatch, caplog):
    s = logsafe.get_settings()
    monkeypatch.setattr(s, "data_go_kr_api_key", "SECRETKEY1234567890")
    logger = logging.getLogger("collect-test")
    caplog.handler.addFilter(logsafe.RedactFilter())
    with caplog.at_level(logging.ERROR):
        logger.error("수집 실패 %s", "https://x?serviceKey=SECRETKEY1234567890")
    assert "SECRETKEY1234567890" not in caplog.text and "serviceKey=***" in caplog.text
