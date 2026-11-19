"""한국천문연구원 일출·일몰·음력: 공식 값 우선, 받지 못하면 계산식 + 출처 표시, 장애 때 재호출 쉼"""

from datetime import date

from app.services import sea_calendar as sc

D = date(2026, 11, 19)


def _reset():
    sc._sun_cache.clear()
    sc._sun_fail.clear()
    sc._lunar_cache.clear()


def test_official_values(monkeypatch):
    _reset()
    calls = []

    def fake(path, params):
        calls.append(path)
        if path.startswith("RiseSet"):
            return {"sunrise": "0717  ", "sunset": "1721  "}
        return {"lunDay": "01"}

    monkeypatch.setattr(sc, "_kasi_item", fake)
    assert sc.prefetch_sun([(37.271, 126.512), (37.262, 126.531)], D) == 1  # 같은 0.1° 격자 → 한 번만
    assert sc.official_sun_times(37.28, 126.51, D) == ("07:17", "17:21", sc.KASI)
    assert len(calls) == 1
    assert sc.mulddae_official(D, west=True) == ("7물", sc.KASI)  # 음력 1일 = 서해 7물


def test_fallback_and_backoff(monkeypatch):
    _reset()
    calls = []
    monkeypatch.setattr(sc, "_kasi_item", lambda path, params: calls.append(path))
    assert sc.official_sun_times(37.25, 126.51, D)[2] == sc.CALC and not calls  # 전체 요약: 바로 부르지 않음
    rise, sset, src = sc.official_sun_times(37.25, 126.51, D, fetch=True)
    assert src == sc.CALC and (rise, sset) == sc.sun_times(37.25, 126.51, D)
    sc.official_sun_times(37.25, 126.51, D, fetch=True)  # 실패 직후 다시 부르지 않음
    assert calls.count("RiseSetInfoService/getLCRiseSetInfo") == 1
    m, src = sc.mulddae_official(D, west=True)
    assert src == sc.CALC and m == sc.mulddae(D, west=True)


def test_rule_unchanged():
    assert [sc.mulddae_name(d, True) for d in (1, 8, 9, 10, 15)] == ["7물", "조금", "무시", "1물", "6물"]
    assert [sc.mulddae_name(d, False) for d in (1, 8, 9, 15)] == ["8물", "조금", "1물", "7물"]


def test_background_prefetch_clears_summary(monkeypatch):
    _reset()
    monkeypatch.setattr(sc, "_kasi_item", lambda path, params: {"sunrise": "0700", "sunset": "1700"})
    done = []
    sc.prefetch_sun_background([(35.1, 129.0)], D, lambda: done.append(1))
    import time

    for _ in range(50):
        if done:
            break
        time.sleep(0.02)
    assert done and sc.official_sun_times(35.1, 129.0, D) == ("07:00", "17:00", sc.KASI)
