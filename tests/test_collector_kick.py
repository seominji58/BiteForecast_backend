from datetime import timedelta

from app.models.base import utcnow
from app.services import collector_kick as ck


def test_should_kick_only_when_stale_and_not_recently_kicked():
    now = utcnow()
    assert not ck.should_kick(now - timedelta(minutes=30), now)
    assert ck.should_kick(now - timedelta(hours=2), now)
    assert ck.should_kick(None, now)
    assert not ck.should_kick(now - timedelta(hours=2), now, last_kick=now - timedelta(minutes=5))
    assert ck.should_kick(now - timedelta(hours=2), now, last_kick=now - timedelta(minutes=20))


class _S:
    def __init__(self, token="", machine="", app=""):
        self.fly_api_token, self.collector_machine_id, self.fly_app_name = token, machine, app


def test_maybe_kick_does_nothing_without_config(monkeypatch):
    monkeypatch.setattr(ck, "get_settings", lambda: _S())
    assert ck.maybe_kick(None) is False


def test_maybe_kick_starts_once(monkeypatch):
    calls = []
    monkeypatch.setattr(ck, "get_settings", lambda: _S("t", "m", "a"))
    monkeypatch.setattr(ck, "_last_kick", None)
    monkeypatch.setattr(ck, "_start_machine", lambda: calls.append(1))
    old = utcnow() - timedelta(hours=3)
    assert ck.maybe_kick(old) is True
    assert ck.maybe_kick(old) is False  # 15분 안 두 번째는 보내지 않음
