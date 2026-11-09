from app.models import Title
from app.services.titles import resolve_title
from tests.conftest import signup

TITLES = [
    Title(name="입문", min_points=0, sort_order=0),
    Title(name="초보", min_points=50, sort_order=1),
    Title(name="주말", min_points=150, sort_order=2),
    Title(name="베테랑", min_points=300, sort_order=3),
    Title(name="바다의 고수", min_points=600, sort_order=4),
]


def test_health(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_me_requires_login(client):
    res = client.get("/api/v1/me/title")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_new_user_starts_at_first_title(client):
    res = client.get("/api/v1/me/title", headers=signup(client))
    assert res.status_code == 200
    body = res.json()
    assert body["total_points"] == 0
    assert body["current"]["name"] == "입문"
    assert body["next"]["name"] == "초보"
    assert body["points_to_next"] == 50


def test_unknown_place_returns_404(client):
    res = client.get("/api/v1/places/9999")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_resolve_title_boundaries():
    assert resolve_title(49, TITLES).current.name == "입문"
    assert resolve_title(50, TITLES).current.name == "초보"
    assert resolve_title(599, TITLES).current.name == "베테랑"
    top = resolve_title(600, TITLES)
    assert top.current.name == "바다의 고수"
    assert top.next is None and top.points_to_next is None
