"""서비스 개선 2단계: 내 기록 요약·첫 포획·최대어, 차단, 신고 검토, 공유 기록 채비 표시"""

from tests.conftest import ADMIN, signup

J = "/api/v1/journals"
C = "/api/v1/community"


def save(client, h, place_id, when, **kw):
    res = client.post(J, json={"place_id": place_id, "fished_at": when, **kw}, headers=h)
    assert res.status_code == 201, res.text
    return res.json()


def test_record_summary_and_milestones(client, places):
    h = signup(client)
    a = save(
        client, h, places[0], "2026-10-01T06:00:00+09:00", species_code="rockfish", count=2, max_length_cm=30
    )
    assert a["milestone"] == {
        "kind": "first_catch",
        "species_name": "우럭(조피볼락)",
        "length_cm": 30.0,
        "previous_cm": None,
    }
    b = save(
        client, h, places[0], "2026-10-08T06:00:00+09:00", species_code="rockfish", count=1, max_length_cm=38
    )
    assert b["milestone"]["kind"] == "personal_best" and b["milestone"]["previous_cm"] == 30.0
    c = save(
        client, h, places[1], "2026-10-08T15:00:00+09:00", species_code="rockfish", count=1, max_length_cm=25
    )
    assert c["milestone"] is None  # 최대어보다 작음
    skunk = save(client, h, places[1], "2026-10-15T06:00:00+09:00", count=0)
    assert skunk["milestone"] is None
    save(client, h, places[2], "2026-10-20T06:00:00+09:00", species_etc="쥐노래미", count=3)

    s = client.get("/api/v1/me/records/summary", headers=h).json()
    assert s["journal_count"] == 5
    assert s["trip_days"] == 4  # 10/08 두 기록은 하루
    assert s["skunk_days"] == 1
    assert [x["species_name"] for x in s["species"]] == ["우럭(조피볼락)", "쥐노래미"]
    rock = s["species"][0]
    assert rock["first_journal_id"] == a["journal"]["id"] and rock["best_journal_id"] == b["journal"]["id"]
    assert rock["best_length_cm"] == 38.0 and rock["catch_count"] == 4 and rock["best_verified"] is False
    assert s["species"][1]["best_length_cm"] is None
    assert client.get("/api/v1/me/records/summary").status_code == 401


def test_block_hides_posts_and_comments(client):
    me, other = signup(client), signup(client)
    p = client.post(
        f"{C}/posts", json={"category": "tip", "title": "차단될 글", "body": "x"}, headers=other
    ).json()
    mine = client.post(
        f"{C}/posts", json={"category": "tip", "title": "내 글", "body": "x"}, headers=me
    ).json()
    client.post(f"{C}/posts/{mine['id']}/comments", json={"body": "차단될 댓글"}, headers=other)

    r = client.post(f"{C}/blocks", json={"target_type": "post", "target_id": p["id"]}, headers=me)
    assert r.status_code == 201, r.text
    ids = [x["id"] for x in client.get(f"{C}/posts", headers=me).json()]
    assert p["id"] not in ids and mine["id"] in ids
    assert client.get(f"{C}/posts/{mine['id']}", headers=me).json()["comments"] == []
    # 다른 사람에게는 그대로 보인다
    assert p["id"] in [x["id"] for x in client.get(f"{C}/posts").json()]
    # 나를 차단할 수는 없다
    assert (
        client.post(
            f"{C}/blocks", json={"target_type": "post", "target_id": mine["id"]}, headers=me
        ).status_code
        == 400
    )

    blocks = client.get(f"{C}/blocks", headers=me).json()
    assert len(blocks) == 1
    assert client.delete(f"{C}/blocks/{blocks[0]['user_id']}", headers=me).status_code == 204
    assert p["id"] in [x["id"] for x in client.get(f"{C}/posts", headers=me).json()]


def test_admin_report_review(client):
    author = signup(client)
    p = client.post(
        f"{C}/posts", json={"category": "tip", "title": "신고될 글", "body": "x"}, headers=author
    ).json()
    target = {"target_type": "post", "target_id": p["id"], "reason": "광고"}
    for _ in range(3):
        client.post(f"{C}/reports", json=target, headers=signup(client))
    assert client.get(f"{C}/posts/{p['id']}").status_code == 404  # 자동 숨김

    assert client.get("/api/v1/admin/reports").status_code in (401, 403)
    items = {
        (i["target_type"], i["target_id"]): i
        for i in client.get("/api/v1/admin/reports", headers=ADMIN).json()
    }
    item = items[("post", p["id"])]
    assert item["report_count"] == 3 and item["hidden"] is True and item["reasons"] == ["광고"] * 3

    res = client.post(
        f"/api/v1/admin/reports/post/{p['id']}/review", json={"action": "restore"}, headers=ADMIN
    )
    assert res.status_code == 200 and res.json()["hidden"] is False
    assert client.get(f"{C}/posts/{p['id']}").status_code == 200
    # 검토한 신고는 다시 세지 않는다: 새 신고 1건으로 바로 숨지 않는다
    client.post(f"{C}/reports", json=target, headers=signup(client))
    assert client.get(f"{C}/posts/{p['id']}").status_code == 200
    assert ("post", p["id"]) in {
        (i["target_type"], i["target_id"]) for i in client.get("/api/v1/admin/reports", headers=ADMIN).json()
    }


def test_shared_journal_tackle(client, places):
    h = signup(client)
    j = save(
        client,
        h,
        places[0],
        "2026-10-02T06:00:00+09:00",
        species_code="rockfish",
        count=1,
        bait="크릴",
        rig="구멍찌",
    )
    shown = client.post(
        f"{C}/posts",
        json={"category": "catch", "title": "채비 공개", "body": "x", "journal_id": j["journal"]["id"]},
        headers=h,
    ).json()
    assert shown["catch"]["bait"] == "크릴" and shown["catch"]["rig"] == "구멍찌"
    j2 = save(
        client, h, places[0], "2026-10-03T06:00:00+09:00", species_code="rockfish", count=1, bait="크릴"
    )
    hidden = client.post(
        f"{C}/posts",
        json={
            "category": "catch",
            "title": "채비 숨김",
            "body": "x",
            "journal_id": j2["journal"]["id"],
            "show_tackle": False,
        },
        headers=h,
    ).json()
    assert hidden["catch"]["bait"] is None and hidden["catch"]["rig"] is None
