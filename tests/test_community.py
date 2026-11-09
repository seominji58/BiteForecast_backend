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


def test_list_has_catch_region_and_filters(client, places):
    h = signup(client)
    a = post(client, h, place_id=places[0], species_code="black_porgy", title="지역 필터 글")
    b = post(client, h, species_etc="쥐노래미", title="어종 직접 입력 글")
    listed = client.get(f"{URL}/posts", headers=h).json()
    item = next(x for x in listed if x["id"] == a["id"])
    assert item["region_name"] == "테스트 해역" and item["place_id"] == places[0] and item["catch"] is None
    only_sido = client.get(f"{URL}/posts", params={"sido": "테스트"}).json()
    assert a["id"] in [x["id"] for x in only_sido] and b["id"] not in [x["id"] for x in only_sido]
    by_code = client.get(f"{URL}/posts", params={"species": "black_porgy"}).json()
    assert [x["id"] for x in by_code if x["id"] in (a["id"], b["id"])] == [a["id"]]
    by_name = client.get(f"{URL}/posts", params={"species": "쥐노래미"}).json()
    assert b["id"] in [x["id"] for x in by_name]


def test_favorites(client, places):
    h = signup(client)
    assert client.get("/api/v1/me/favorites").status_code == 401
    assert client.put(f"/api/v1/me/favorites/{places[1]}", headers=h).status_code == 204
    assert client.put(f"/api/v1/me/favorites/{places[1]}", headers=h).status_code == 204  # 중복 무시
    assert client.put("/api/v1/me/favorites/99999", headers=h).status_code == 404
    favs = client.get("/api/v1/me/favorites", headers=h).json()
    assert [f["id"] for f in favs] == [places[1]]
    assert client.delete(f"/api/v1/me/favorites/{places[1]}", headers=h).status_code == 204
    assert client.get("/api/v1/me/favorites", headers=h).json() == []
