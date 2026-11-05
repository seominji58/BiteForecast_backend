"""개발용 샘플 데이터 — 실제 해역(D-3)이 정해지기 전 화면·일지 개발에 쓴다.

장소 이름·좌표는 실제 낚시터가 아니다. 실제 시드가 준비되면 이 데이터는 쓰지 않는다.

실행: python -m seeds.dev_sample
"""

from sqlalchemy import select

from app.core.db import SessionLocal, init_db
from app.models import Place, Region
from app.models.enums import PlaceType

SAMPLE = {
    "샘플 해역 A": [("샘플 방파제 A-1", PlaceType.BREAKWATER), ("샘플 갯바위 A-2", PlaceType.ROCK)],
    "샘플 해역 B": [("샘플 선착장 B-1", PlaceType.WHARF), ("샘플 해변 B-2", PlaceType.BEACH)],
}


def main() -> None:
    init_db()
    with SessionLocal() as db:
        if db.scalar(select(Region.id).where(Region.name.like("샘플 해역%")).limit(1)):
            print("샘플 데이터가 이미 있습니다.")
            return
        for region_name, places in SAMPLE.items():
            region = Region(name=region_name)
            region.places = [Place(name=n, type=t, lat=None, lon=None) for n, t in places]
            db.add(region)
        db.commit()
        print("샘플 해역 2곳, 장소 4곳을 추가했습니다.")


if __name__ == "__main__":
    main()
