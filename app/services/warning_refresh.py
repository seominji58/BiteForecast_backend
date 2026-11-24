"""해상 특보를 15분 안쪽으로 신선하게 유지한다 (2026-11-20).

수집기(Fly 예약 머신)는 매시간만 돈다. Fly 예약은 「매시간」보다 짧게 못 잡고,
머신을 계속 켜 두면 비용이 든다. 그래서 앱이 특보를 읽을 때 마지막 스냅샷이
15분보다 오래됐으면 API 서버가 뒤에서 한 번 받아 저장한다.

- 지금 요청은 기다리지 않는다 (기존 스냅샷으로 응답, 다음 요청부터 새 자료)
- 동시에 하나만 받는다. 실패하면 5분 동안 다시 시도하지 않는다 (호출량 보호)
- 운영 환경 + 인증키가 있을 때만 켠다 (테스트·로컬에서 외부 호출 없음)
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import MarineWarningSnapshot
from app.models.base import utcnow

log = logging.getLogger("warning_refresh")

REFRESH_AFTER = timedelta(minutes=15)
RETRY_AFTER_FAIL_SECONDS = 300
KEEP_SNAPSHOTS = 96  # 15분마다면 약 하루치. 판정은 최신 1건만 쓴다

WAIT_IF_OLDER = timedelta(minutes=30)
WAIT_SECONDS = 2.0

_lock = threading.Lock()
_done = threading.Event()
_done.set()
_running = False
# monotonic 은 「부팅 뒤 초」라 막 켜진 서버에선 작다 → 0 대신 None
# (켜진 뒤 5분간 특보 갱신이 막히던 버그, 2026-11-24)
_last_fail: float | None = None
_listeners: list[Callable[[], None]] = []


def on_refreshed(fn: Callable[[], None]) -> None:
    """새 특보를 저장한 뒤 부를 함수 (예: 전체 요약 캐시 비우기)"""
    _listeners.append(fn)


def store_snapshot(db: Session, st) -> None:
    """특보 현황 1건 저장 + 오래된 스냅샷 정리. 수집기와 API 서버가 같이 쓴다. commit 은 호출한 쪽"""
    db.add(
        MarineWarningSnapshot(
            issued_at=st.issued_at,
            fetched_at=utcnow(),
            active_json=json.dumps([asdict(w) for w in st.active], ensure_ascii=False),
            preliminary_json=json.dumps([asdict(p) for p in st.preliminary], ensure_ascii=False),
            raw_active=st.raw_active,
            raw_preliminary=st.raw_preliminary,
        )
    )
    db.flush()
    old = db.scalars(
        select(MarineWarningSnapshot.id)
        .order_by(MarineWarningSnapshot.fetched_at.desc())
        .offset(KEEP_SNAPSHOTS)
    ).all()
    if old:
        db.execute(delete(MarineWarningSnapshot).where(MarineWarningSnapshot.id.in_(old)))


def _enabled() -> bool:
    from app.core.config import get_settings

    s = get_settings()
    return s.app_env == "prod" and bool(s.data_go_kr_api_key)


def needs_refresh(fetched_at: datetime | None, now: datetime | None = None) -> bool:
    if fetched_at is None:
        return True
    return (now or utcnow()) - fetched_at > REFRESH_AFTER


def maybe_refresh(
    fetched_at: datetime | None,
    *,
    enabled: Callable[[], bool] = _enabled,
    fetch: Callable[[], None] | None = None,
) -> bool:
    """오래됐으면 뒤에서 새로 받기 시작한다. 시작했으면 True"""
    global _running
    if not needs_refresh(fetched_at) or not enabled():
        return False
    with _lock:
        if _running or (_last_fail is not None and time.monotonic() - _last_fail < RETRY_AFTER_FAIL_SECONDS):
            return False
        _running = True
        _done.clear()
    threading.Thread(
        target=_run, args=(fetch or _fetch_and_store,), daemon=True, name="warning-refresh"
    ).start()
    return True


def _run(fetch: Callable[[], None]) -> None:
    global _running, _last_fail
    began = time.monotonic()
    try:
        fetch()
        log.info("특보 새로 받음 (%.1fs)", time.monotonic() - began)
        for fn in _listeners:
            fn()
    except Exception as e:  # 뒤에서 도는 작업: 실패해도 요청·서버에 영향 없게
        _last_fail = time.monotonic()
        log.error("특보 새로 받기 실패: %s: %s", type(e).__name__, e)
    finally:
        with _lock:
            _running = False
            _done.set()


def should_wait(fetched_at: datetime | None, now: datetime | None = None) -> bool:
    """아주 오래된(30분↑) 특보면 이번 요청이 새로 받을 때까지 잠깐 기다린다"""
    return fetched_at is None or (now or utcnow()) - fetched_at > WAIT_IF_OLDER


def wait_for_refresh(timeout: float = WAIT_SECONDS) -> bool:
    """진행 중인 갱신이 끝나길 최대 timeout 초 기다린다. 끝났으면 True"""
    return _done.wait(timeout)


def _fetch_and_store() -> None:
    from app.clients.kma_warning import KmaWarningClient
    from app.core.db import SessionLocal

    client = KmaWarningClient()
    try:
        st = client.status()
    finally:
        client.close()
    with SessionLocal() as db:
        store_snapshot(db, st)
        db.commit()
