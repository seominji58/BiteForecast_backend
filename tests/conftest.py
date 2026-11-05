import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["APP_ENV"] = "test"

import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Place, Region  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def places(client) -> list[int]:
    """테스트용 장소 3곳 (세션 동안 공유, 사용자는 테스트마다 새 기기 ID 로 분리)"""
    with SessionLocal() as db:
        region = Region(name="테스트 해역")
        region.places = [Place(name=f"테스트 장소 {i}") for i in range(3)]
        db.add(region)
        db.commit()
        return [p.id for p in region.places]


@pytest.fixture()
def device():
    """새 사용자 = 새 기기 ID"""
    return {"X-Device-Id": str(uuid.uuid4())}
