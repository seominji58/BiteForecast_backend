"""커뮤니티: 작성·목록·댓글·좋아요·신고 숨김·권한"""

from tests.conftest import signup

URL = "/api/v1/community"


def post(client, h, **kw):
    body = {
        "category": "catch",
        "title": "감성돔 입질 시작",
        "body": "오전 간조 전후로 입질이 있었습니다.",
        **kw,
    }
    r = client.post(f"{URL}/posts", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_list_and_detail(client, places):
    h = signup(client)
    p = post(client, h, place_id=places[0], species_code="black_porgy")
    assert p["author"]["nickname"].startswith("t") and p["author"]["title"] == "입문"
    assert p["place_name"] == "테스트 장소 0" and p["species_name"] == "감성돔"
    assert p["mine"] is True and p["comments"] == []

    other = signup(client)
    listed = client.get(f"{URL}/posts", params={"category": "catch"}, headers=other).json()
    item = next(x for x in listed if x["id"] == p["id"])
    assert item["mine"] is False and item["excerpt"].startswith("오전")
    assert all(x["category"] == "catch" for x in listed)


def test_validation(client):
    h = signup(client)
    assert (
        client.post(
            f"{URL}/posts", json={"category": "catch", "title": " ", "body": "x"}, headers=h
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{URL}/posts", json={"category": "nope", "title": "제목", "body": "x"}, headers=h
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{URL}/posts",
            json={"category": "tip", "title": "제목", "body": "x", "place_id": 99999},
            headers=h,
        ).status_code
        == 400
    )


def test_comment_like_and_counts(client):
    a, b = signup(client), signup(client)
    p = post(client, a)
    d = client.post(f"{URL}/posts/{p['id']}/comments", json={"body": "축하드려요!"}, headers=b).json()
    assert d["comment_count"] == 1 and d["comments"][0]["mine"] is True

    assert client.put(f"{URL}/posts/{p['id']}/like", headers=b).json() == {"liked": True, "like_count": 1}
    assert client.put(f"{URL}/posts/{p['id']}/like", headers=b).json()["like_count"] == 1  # 중복 좋아요 없음
    assert client.delete(f"{URL}/posts/{p['id']}/like", headers=b).json() == {"liked": False, "like_count": 0}


def test_only_author_can_delete(client):
    a, b = signup(client), signup(client)
    p = post(client, a)
    assert client.delete(f"{URL}/posts/{p['id']}", headers=b).status_code == 403
    assert client.delete(f"{URL}/posts/{p['id']}", headers=a).status_code == 204
    assert client.get(f"{URL}/posts/{p['id']}", headers=a).status_code == 404


def test_reports_hide_after_threshold(client):
    author = signup(client)
    p = post(client, author)
    target = {"target_type": "post", "target_id": p["id"], "reason": "광고"}
    assert client.post(f"{URL}/reports", json=target, headers=author).status_code == 400  # 자기 글 신고 불가

    reporters = [signup(client), signup(client), signup(client)]
    r1 = client.post(f"{URL}/reports", json=target, headers=reporters[0]).json()
    assert r1 == {"status": "received", "hidden": False}
    assert (
        client.post(f"{URL}/reports", json=target, headers=reporters[0]).json()["status"]
        == "already_reported"
    )
    client.post(f"{URL}/reports", json=target, headers=reporters[1])
    r3 = client.post(f"{URL}/reports", json=target, headers=reporters[2]).json()
    assert r3["hidden"] is True

    # 다른 사람에게는 숨김, 작성자는 계속 볼 수 있음
    assert client.get(f"{URL}/posts/{p['id']}", headers=signup(client)).status_code == 404
    assert client.get(f"{URL}/posts/{p['id']}", headers=author).status_code == 200


def test_popular_sort(client):
    a = signup(client)
    quiet = post(client, a, title="조용한 글")
    hot = post(client, a, title="인기 있는 글")
    for _ in range(2):
        client.put(f"{URL}/posts/{hot['id']}/like", headers=signup(client))
    ids = [
        x["id"] for x in client.get(f"{URL}/posts", params={"sort": "popular"}, headers=signup(client)).json()
    ]
    assert ids.index(hot["id"]) < ids.index(quiet["id"])
