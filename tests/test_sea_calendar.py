"""물때(달력 계산)·일출·일몰 — 바다타임 물때표 날짜와 대조"""

from datetime import date

import pytest

from app.services.sea_calendar import lunar_day, mulddae, sun_times


@pytest.mark.parametrize(
    "solar,lunar",
    [
        (date(2026, 7, 14), 1),
        (date(2026, 7, 15), 2),
        (date(2026, 7, 19), 6),
        (date(2026, 8, 7), 25),
        (date(2026, 8, 8), 26),
        (date(2026, 8, 20), 8),
        (date(2026, 6, 13), 28),
    ],
)
def test_lunar_day_matches_badatime(solar, lunar):
    assert lunar_day(solar) == lunar


def test_mulddae_tables():
    # 음력 1일(2026-07-14): 서해 7물 / 남해 8물, 음력 8일(08-20): 둘 다 조금
    assert (mulddae(date(2026, 7, 14), True), mulddae(date(2026, 7, 14), False)) == ("7물", "8물")
    assert (mulddae(date(2026, 8, 20), True), mulddae(date(2026, 8, 20), False)) == ("조금", "조금")
    # 음력 9일(08-21): 서해 무시 / 남해 1물
    assert (mulddae(date(2026, 8, 21), True), mulddae(date(2026, 8, 21), False)) == ("무시", "1물")


def test_sun_times_seoul_november():
    rise, sset = sun_times(37.5665, 126.978, date(2026, 11, 17))
    assert "07:08" <= rise <= "07:18" and "17:15" <= sset <= "17:25"
