"""장소 검색: 이름·지역명·주소 (FR-01)"""

import pytest

from app.core.db import SessionLocal
from app.models import Place, PlaceInfo, Region
from app.models.enums import PlaceType

URL = "/api/v1/places"


@pytest.fixture(scope="module")
def paid_place(client):
    with SessionLocal() as db:
        region = Region(name="충남 검색군")
        p = Place(name="검색테스트 좌대낚시터", type=PlaceType.PAID, lat=36.5, lon=126.3)
        region.places = [p]
        db.add(region)
        db.flush()
        db.add(
            PlaceInfo(
                place_id=p.id,
                source="전국낚시터정보표준데이터",
                address="충청남도 검색군 바다면 1",
                fee="1일 5만원",
            )
        )
        db.commit()
        return p.id


def test_search_by_name_region_and_address(client, paid_place):
    for q in ("좌대낚시터", "검색군", "바다면"):
        ids = [p["id"] for p in client.get(URL, params={"q": q}).json()]
        assert paid_place in ids, q
    assert client.get(URL, params={"q": "없는지역이름"}).json() == []


def test_place_fields_and_detail(client, paid_place):
    p = next(x for x in client.get(URL, params={"q": "좌대"}).json() if x["id"] == paid_place)
    assert p["region_name"] == "충남 검색군" and p["type"] == "paid" and p["address"].startswith("충청남도")
    d = client.get(f"{URL}/{paid_place}").json()
    assert d["info"]["fee"] == "1일 5만원" and d["info"]["source"] == "전국낚시터정보표준데이터"
