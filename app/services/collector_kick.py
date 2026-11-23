"""수집기 깨우기 (2026-11-23).

Fly 예약 머신(schedule=hourly)이 가끔 몇 시간씩 실행되지 않는다 (2026-11-23 15:19~19:13 한 번도 안 돎).
그래서 API 가 화면 요청을 받을 때 마지막 수집이 오래됐으면 수집기 머신을 직접 시작한다.

- 조건: 마지막 예보 수집이 KICK_AFTER(75분)보다 오래됨
- 시작 요청은 KICK_EVERY(15분)에 한 번만 (요청이 몰려도 한 번)
- 백그라운드 스레드에서 보내 화면 응답을 늦추지 않는다. 실패해도 조용히 넘긴다 (로그만)
- FLY_API_TOKEN·COLLECTOR_MACHINE_ID 가 없으면 아무것도 안 한다 (로컬·테스트)
"""

import logging
import threading
from datetime import datetime, timedelta

import httpx

from app.core.config import get_settings
from app.models.base import utcnow

log = logging.getLogger(__name__)

KICK_AFTER = timedelta(minutes=75)
KICK_EVERY = timedelta(minutes=15)

_lock = threading.Lock()
_last_kick: datetime | None = None


def _enabled() -> bool:
    s = get_settings()
    return bool(s.fly_api_token and s.collector_machine_id and s.fly_app_name)


def should_kick(
    last_collected: datetime | None, now: datetime | None = None, last_kick: datetime | None = None
) -> bool:
    now = now or utcnow()
    if last_collected is not None and now - last_collected <= KICK_AFTER:
        return False
    return last_kick is None or now - last_kick > KICK_EVERY


def maybe_kick(last_collected: datetime | None) -> bool:
    """오래됐으면 수집기 시작을 요청한다. 요청을 보냈으면 True"""
    global _last_kick
    if not _enabled():
        return False
    with _lock:
        now = utcnow()
        if not should_kick(last_collected, now, _last_kick):
            return False
        _last_kick = now
    threading.Thread(target=_start_machine, name="collector-kick", daemon=True).start()
    return True


def _start_machine() -> None:
    s = get_settings()
    url = f"https://api.machines.dev/v1/apps/{s.fly_app_name}/machines/{s.collector_machine_id}/start"
    try:
        r = httpx.post(url, headers={"Authorization": f"Bearer {s.fly_api_token}"}, timeout=10)
        # 이미 실행 중이면 오류 코드가 오지만 목적(수집 중)은 이뤄진 것
        log.info("수집기 깨우기 요청: %s %s", r.status_code, r.text[:200])
    except httpx.HTTPError as e:
        log.warning("수집기 깨우기 실패: %s", e)
