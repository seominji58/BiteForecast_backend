import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["APP_ENV"] = "test"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp(prefix="bf-media-")

import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Place, Region  # noqa: E402


@pytest.fixture(autouse=True)
def collector_file(tmp_path, monkeypatch):
    """실제 runtime/collector-status.json 대신 테스트마다 빈 상태 파일을 읽는다"""
    from app.jobs import collector_status

    path = tmp_path / "collector-status.json"
    monkeypatch.setattr(collector_status, "STATUS_PATH", path)
    return path


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


AGREE = {"over_14": True, "terms": True, "privacy": True}


def signup(client, device_id: str | None = None, **kw) -> dict:
    """새 회원(이메일 가입)으로 로그인한 요청 헤더. 기기 ID 도 함께 보낸다"""
    device_id = device_id or str(uuid.uuid4())
    tag = uuid.uuid4().hex[:10]
    body = {
        "email": f"u{tag}@test.kr",
        "password": "fish1234",
        "nickname": f"t{tag}",
        "agreements": AGREE,
        **kw,
    }
    res = client.post("/api/v1/auth/signup", json=body, headers={"X-Device-Id": device_id})
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['token']}", "X-Device-Id": device_id}


@pytest.fixture()
def device(client):
    """새 회원으로 로그인한 헤더 (테스트마다 새 사용자)"""
    return signup(client)


ADMIN = {"X-Admin-Token": "test-admin-token"}


def make_jpeg(color=(30, 120, 160), size=(64, 48), taken: str | None = None, gps: bool = False) -> bytes:
    """테스트용 JPEG. taken="2026:11:01 06:30:00" 이면 EXIF 촬영 시각, gps=True 면 위치 정보 포함"""
    import io

    from PIL import Image

    img = Image.new("RGB", size, color)
    exif = Image.Exif()
    if taken:
        exif.get_ifd(0x8769)[36867] = taken
    if gps:
        exif.get_ifd(0x8825).update({1: "N", 2: (37.0, 30.0, 0.0), 3: "E", 4: (126.0, 58.0, 0.0)})
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def upload(client, device, purpose="journal", data: bytes | None = None, **kw) -> dict:
    res = client.post(
        "/api/v1/photos",
        files={"file": ("a.jpg", data or make_jpeg(**kw), "image/jpeg")},
        data={"purpose": purpose},
        headers=device,
    )
    assert res.status_code == 201, res.text
    return res.json()
