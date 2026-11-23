"""특보 15분 갱신 (services/warning_refresh.py)"""

import threading
import time
from datetime import timedelta

from app.models.base import utcnow
from app.services import warning_refresh as wr


def _reset():
    wr._running = False
    wr._last_fail = 0.0


def _wait():
    for _ in range(100):
        if not wr._running:
            return
        time.sleep(0.01)


def test_needs_refresh():
    now = utcnow()
    assert wr.needs_refresh(None, now)
    assert not wr.needs_refresh(now - timedelta(minutes=10), now)
    assert wr.needs_refresh(now - timedelta(minutes=16), now)


def test_fresh_snapshot_does_nothing():
    _reset()
    calls = []
    started = wr.maybe_refresh(utcnow(), enabled=lambda: True, fetch=lambda: calls.append(1))
    assert not started and calls == []


def test_disabled_outside_prod():
    _reset()
    assert not wr.maybe_refresh(None, fetch=lambda: None)  # 테스트 환경은 app_env=dev


def test_single_flight_and_listener():
    _reset()
    gate = threading.Event()
    calls, cleared = [], []
    wr.on_refreshed(lambda: cleared.append(1))
    try:
        old = utcnow() - timedelta(hours=1)

        def fetch():
            calls.append(1)
            gate.wait(2)

        assert wr.maybe_refresh(old, enabled=lambda: True, fetch=fetch)
        assert not wr.maybe_refresh(old, enabled=lambda: True, fetch=fetch)  # 받는 중이면 또 시작 안 함
        gate.set()
        _wait()
        assert calls == [1] and cleared == [1]
    finally:
        wr._listeners.pop()


def test_failure_backs_off():
    _reset()

    def boom():
        raise RuntimeError("down")

    old = utcnow() - timedelta(hours=1)
    assert wr.maybe_refresh(old, enabled=lambda: True, fetch=boom)
    _wait()
    assert not wr._running
    assert not wr.maybe_refresh(old, enabled=lambda: True, fetch=boom)  # 5분 동안 다시 안 함
    _reset()


def test_store_snapshot_keeps_recent():
    """공용 테스트 DB 를 건드리지 않게 메모리 DB 에서 확인"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.clients.kma_warning import WarningStatus
    from app.models import MarineWarningSnapshot

    engine = create_engine("sqlite://")
    MarineWarningSnapshot.__table__.create(engine)
    with Session(engine) as db:
        for _ in range(wr.KEEP_SNAPSHOTS + 3):
            wr.store_snapshot(db, WarningStatus(issued_at=None))
        db.commit()
        assert db.query(MarineWarningSnapshot).count() == wr.KEEP_SNAPSHOTS


def test_wait_for_refresh_and_should_wait():
    _reset()
    now = utcnow()
    assert wr.should_wait(None) and wr.should_wait(now - timedelta(minutes=31), now)
    assert not wr.should_wait(now - timedelta(minutes=20), now)
    gate = threading.Event()
    assert wr.maybe_refresh(now - timedelta(hours=1), enabled=lambda: True, fetch=lambda: gate.wait(2))
    assert not wr.wait_for_refresh(0.05)  # 아직 받는 중
    gate.set()
    assert wr.wait_for_refresh(1.0)
    _reset()
