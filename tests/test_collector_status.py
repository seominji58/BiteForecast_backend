from collections import Counter


def test_cycle_retries_then_records_success(tmp_path, monkeypatch):
    from app.jobs import collect, collector_status

    path = tmp_path / "collector.json"
    monkeypatch.setattr(collector_status, "STATUS_PATH", path)
    monkeypatch.setattr(collect, "read_status", lambda: collector_status.read_status(path))
    monkeypatch.setattr(collect, "write_status", lambda value: collector_status.write_status(value, path))
    calls = 0

    def flaky():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary")
        return Counter(forecast_rows=10)

    slept = []
    state, stats = collect.run_cycle(collect=flaky, retry_delays=(2,), sleep=slept.append)
    saved = collector_status.read_status(path)
    assert state == "success" and stats == Counter(forecast_rows=10)
    assert calls == 2 and slept == [2]
    assert saved["state"] == "success" and saved["last_success_at"]
    assert saved["stats"] == {"forecast_rows": 10}


def test_cycle_records_partial_without_advancing_success(tmp_path, monkeypatch):
    from app.jobs import collect, collector_status

    path = tmp_path / "collector.json"
    collector_status.write_status({"last_success_at": "2026-11-10T00:00:00"}, path)
    monkeypatch.setattr(collect, "read_status", lambda: collector_status.read_status(path))
    monkeypatch.setattr(collect, "write_status", lambda value: collector_status.write_status(value, path))

    state, _ = collect.run_cycle(
        collect=lambda: Counter(warning_errors=1), retry_delays=(), sleep=lambda _: None
    )
    saved = collector_status.read_status(path)
    assert state == "partial"
    assert saved["last_success_at"] == "2026-11-10T00:00:00"
    assert saved["last_error"] == "일부 데이터셋 수집 실패"


def test_cycle_exhausts_retries_and_redacts_secret(tmp_path, monkeypatch):
    from app.jobs import collect, collector_status

    path = tmp_path / "collector.json"
    monkeypatch.setattr(collect, "read_status", lambda: collector_status.read_status(path))
    monkeypatch.setattr(collect, "write_status", lambda value: collector_status.write_status(value, path))

    def fail():
        raise RuntimeError("https://example.test?serviceKey=secret-value")

    state, stats = collect.run_cycle(collect=fail, retry_delays=(0, 0), sleep=lambda _: None)
    saved = collector_status.read_status(path)
    assert state == "failed" and stats is None
    assert saved["attempt"] == 3 and saved["consecutive_failures"] == 1
    assert "secret-value" not in saved["last_error"] and "serviceKey=***" in saved["last_error"]


def test_cycle_records_warning_collection_separately(tmp_path, monkeypatch):
    """특보 수집 결과는 데이터셋 단위로 남고, 수집기 전체 실패 주기에는 갱신되지 않는다"""
    from app.jobs import collect, collector_status

    path = tmp_path / "collector.json"
    monkeypatch.setattr(collect, "read_status", lambda: collector_status.read_status(path))
    monkeypatch.setattr(collect, "write_status", lambda value: collector_status.write_status(value, path))

    collect.run_cycle(collect=lambda: Counter(warning_errors=1), retry_delays=(), sleep=lambda _: None)
    saved = collector_status.read_status(path)
    assert saved["warning_collection"]["ok"] is False
    failed_at = saved["warning_collection"]["at"]

    def boom():
        raise RuntimeError("tide stage crashed")

    collect.run_cycle(collect=boom, retry_delays=(), sleep=lambda _: None)
    saved = collector_status.read_status(path)
    assert saved["state"] == "failed"
    # 이전 주기 통계를 이번 결과처럼 남기지 않는다
    assert saved["stats"] is None
    # 특보 수집 결과는 마지막으로 특보를 호출한 주기 그대로
    assert saved["warning_collection"] == {"ok": False, "at": failed_at}

    collect.run_cycle(collect=lambda: Counter(warning_snapshots=1), retry_delays=(), sleep=lambda _: None)
    assert collector_status.read_status(path)["warning_collection"]["ok"] is True
