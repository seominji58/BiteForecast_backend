"""어종별 공식 낚시지수 (홈 어종 탐색): 발표값만, 거리·위치 정책"""

from app.core.db import SessionLocal
from app.core.timeutil import today_kst
from app.models import FishingIndex, Place, PlaceStation, Region, Station
from app.models.base import utcnow
from app.models.enums import StationKind, StationRole
from tests.test_query_budget import count_queries


def _setup(ext="FI_DAY"):
    with SessionLocal() as db:
        st = Station(
            provider="KHOA", external_id=ext, name="지수지점-테스트", kind=StationKind.FISHING_INDEX
        )
        r = Region(name="전남 여수시")
        official = Place(name="지점-공식", lat=34.6, lon=127.7)
        near = Place(name="지점-근처", lat=34.62, lon=127.72)
        far = Place(name="지점-먼곳", lat=34.9, lon=127.9)
        r.places = [official, near, far]
        db.add_all([st, r])
        db.flush()
        for p, km in ((official, 0.0), (near, 6.0), (far, 25.0)):
            db.add(
                PlaceStation(place_id=p.id, role=StationRole.FISHING_INDEX, station_id=st.id, distance_km=km)
            )
        now = utcnow()
        # 우럭: 오전만 발표 / 감성돔: 오전·오후 / 「-」: 어종 공통 / 등급 없는 행
        for period, species, idx in [
            ("오전", "우럭", "좋음"),
            ("오전", "감성돔", "보통"),
            ("오후", "감성돔", "매우좋음"),
            ("오후", "-", "나쁨"),
            ("오후", "볼락", None),
        ]:
            db.add(FishingIndex(station_id=st.id, day=today_kst(), period=period, species=species, index=idx,
                                tide_phase="대조기", fetched_at=now))
        db.commit()
        return st.id, official.id, near.id, far.id


def test_day_index_official_values_only(client):
    sid, official, near, far = _setup()
    with count_queries() as n:
        r = client.get(f"/api/v1/fishing-index?date={today_kst()}")
    assert r.status_code == 200
    assert n[0] <= 20
    d = r.json()
    p = next(x for x in d["points"] if x["station_id"] == sid)
    sp = {s["species"]: s["grades"] for s in p["species"]}
    # 발표된 시간대만 — 우럭 오후 등급을 만들지 않음, 등급 없는 볼락은 빠짐
    assert sp["우럭"] == {"오전": "좋음"}
    assert sp["감성돔"] == {"오전": "보통", "오후": "매우좋음"}
    assert sp["어종 공통"] == {"오후": "나쁨"}
    assert "볼락" not in sp
    assert p["tide_phase"] == {"오전": "대조기", "오후": "대조기"}
    # 공식 지점 자체 / 10km 이내 일반 낚시터(참고) / 25km 는 연결 안 함
    links = {x["place_id"]: x["official"] for x in p["places"]}
    assert links == {official: True, near: False}
    assert "보장하지 않아요" in d["disclaimer"]


def test_day_index_excludes_suspect_places(client, monkeypatch):
    sid, official, near, far = _setup("FI_DAY2")
    import app.services.fishing_index as fi
    from app.services.location import LocationCtx

    real = fi.location_ctx

    def fake(db):
        c = real(db)
        return LocationCtx(
            suspects=c.suspects | {near}, holds=c.holds, coords=c.coords, station_seas=c.station_seas
        )

    monkeypatch.setattr(fi, "location_ctx", fake)
    d = client.get(f"/api/v1/fishing-index?date={today_kst()}").json()
    p = next(x for x in d["points"] if x["station_id"] == sid)
    assert [x["place_id"] for x in p["places"]] == [official]
