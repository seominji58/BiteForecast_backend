"""로그에 비밀값(공공데이터 인증키·관리자 토큰)이 남지 않게 하는 필터 (NFR-03).

외부 API 오류 메시지·예외에 요청 URL 이 섞여 들어와도 키 문자열을 *** 로 바꾼다.
수집기·서버 모두 시작할 때 install() 을 부른다.
"""

import logging
import re

from app.core.config import get_settings

# 공공데이터포털 URL 의 serviceKey=… 는 값이 무엇이든 가린다 (설정에 없는 예전 키 대비)
_QUERY_KEY = re.compile(r"(serviceKey|authKey|apiKey)=([^&\s\"']+)", re.IGNORECASE)


def _secrets() -> list[str]:
    s = get_settings()
    return [v for v in (s.data_go_kr_api_key, s.kma_api_key, s.admin_token) if v and len(v) >= 8]


def redact(text: str) -> str:
    for v in _secrets():
        text = text.replace(v, "***")
    return _QUERY_KEY.sub(lambda m: f"{m.group(1)}=***", text)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        if record.exc_info and record.exc_info[1] is not None:
            # 예외 문자열도 가린다 (traceback 출력 시)
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        return True


def install() -> None:
    """루트 로거의 모든 핸들러에 필터를 단다 (중복 설치 방지)"""
    root = logging.getLogger()
    targets = root.handlers or [logging.lastResort]
    for h in targets:
        if h is not None and not any(isinstance(f, RedactFilter) for f in h.filters):
            h.addFilter(RedactFilter())
    # httpx 는 INFO 에서 요청 URL 전체를 찍는다 → 경고 이상만
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
