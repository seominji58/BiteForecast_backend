from datetime import date, datetime, timedelta

from app.services import nifs_live as n

KST = n.KST


def test_parse_risa_surface_only_and_skip_maintenance():
    codes = [
        {
            "sta_cde": "a",
            "sta_nam_kor": "기장",
            "gru_nam": "남해",
            "lat": "35.2",
            "lon": "129.2",
            "sur_tmp_yn": "Y",
        },
        {
            "sta_cde": "b",
            "sta_nam_kor": "점검",
            "gru_nam": "남해",
            "lat": "35.0",
            "lon": "129.0",
            "sur_tmp_yn": "Y",
        },
    ]
    obs = [
        {
            "sta_cde": "a",
            "obs_dat": "2026-11-24",
            "obs_tim": "09:30:00",
            "obs_lay": "1",
            "wtr_tmp": "16.0",
            "rpr_yn": "N",
        },
        {
            "sta_cde": "a",
            "obs_dat": "2026-11-24",
            "obs_tim": "09:30:00",
            "obs_lay": "3",
            "wtr_tmp": "15.0",
            "rpr_yn": "N",
        },
        {
            "sta_cde": "b",
            "obs_dat": "2026-11-24",
            "obs_tim": "09:30:00",
            "obs_lay": "1",
            "wtr_tmp": "17.0",
            "rpr_yn": "Y",
        },
    ]
    st = {s.code: s for s in n.parse_risa(codes, obs)}
    assert st["a"].temp == 16.0 and st["b"].temp is None


def test_nearest_temp_same_sea_fresh_within_20km():
    now = datetime(2026, 11, 24, 10, 0, tzinfo=KST)
    near = n.RisaStation("a", "기장", "남해", 35.2, 129.2, 16.0, now - timedelta(minutes=30))
    old = n.RisaStation("b", "오래됨", "남해", 35.2, 129.21, 18.0, now - timedelta(hours=5))
    km, st = n.nearest_temp([near, old], 35.25, 129.2, "남해", now)
    assert st.code == "a" and km < 10
    assert n.nearest_temp([near], 35.25, 129.2, "동해", now) is None
    assert n.nearest_temp([near], 36.5, 129.2, "남해", now) is None


def test_recent_redtide_window():
    items = [{"day_report": "20261120", "cod_news": "1"}, {"day_report": "20260916", "cod_news": "2"}]
    got = n.recent_redtide(items, date(2026, 11, 24))
    assert [r["cod_news"] for r in got] == ["1"]


def test_marine_issues_empty_without_keys(client):
    r = client.get("/api/v1/meta/marine-issues")
    assert r.status_code == 200 and r.json()["redtide"] == [] and r.json()["source"] == "국립수산과학원"
