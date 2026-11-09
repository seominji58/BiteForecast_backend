"""사진 업로드·EXIF 제거·접근 권한·관리자 검토·인증 기록 공유 (재설계 v2 §7, §9)"""

import io

from PIL import Image

from tests.conftest import ADMIN, make_jpeg, signup, upload

J = "/api/v1/journals"
P = "/api/v1/community/posts"


def journal(client, device, place_id, **kw) -> dict:
    payload = {"place_id": place_id, "fished_at": "2026-11-01T06:00:00+09:00", **kw}
    res = client.post(J, json=payload, headers=device)
    assert res.status_code == 201, res.text
    return res.json()["journal"]


def test_upload_strips_exif_and_reads_taken_time(client, device):
    ph = upload(client, device, taken="2026:11:01 06:30:00", gps=True, size=(3000, 2000))
    assert ph["url"] == f"/photos/{ph['id']}"
    assert max(ph["width"], ph["height"]) == 1600  # 축소 저장

    img = Image.open(io.BytesIO(client.get(f"/api/v1{ph['url']}", headers=device).content))
    exif = img.getexif()
    assert len(exif) == 0 and not exif.get_ifd(0x8825)  # EXIF·GPS 없음


def test_upload_validation(client, device):
    bad = client.post(
        "/api/v1/photos",
        files={"file": ("a.jpg", b"not an image", "image/jpeg")},
        data={"purpose": "post"},
        headers=device,
    )
    assert bad.status_code == 400
    wrong_purpose = client.post(
        "/api/v1/photos",
        files={"file": ("a.jpg", make_jpeg(), "image/jpeg")},
        data={"purpose": "x"},
        headers=device,
    )
    assert wrong_purpose.status_code == 422


def test_private_photo_access(client, device, places):
    ph = upload(client, device)
    other = signup(client)
    client.get("/api/v1/me/title", headers=other)  # 다른 사용자 생성
    assert client.get(f"/api/v1{ph['url']}", headers=device).status_code == 200
    assert client.get(f"/api/v1{ph['url']}", headers=other).status_code == 404
    assert client.get(f"/api/v1{ph['url']}").status_code == 404
    # 남의 사진은 내 일지에 붙일 수 없다
    res = client.post(
        J,
        json={"place_id": places[0], "fished_at": "2026-11-01T06:00:00+09:00", "photo_ids": [ph["id"]]},
        headers=other,
    )
    assert res.status_code == 400
    # 게시글용 사진은 일지에 붙일 수 없다 (용도 구분)
    post_photo = upload(client, device, purpose="post")
    res = client.post(
        J,
        json={
            "place_id": places[0],
            "fished_at": "2026-11-01T06:00:00+09:00",
            "photo_ids": [post_photo["id"]],
        },
        headers=device,
    )
    assert res.status_code == 400


def test_max_four_photos(client, device, places):
    ids = [upload(client, device, color=(i * 40, 10, 10))["id"] for i in range(5)]
    res = client.post(
        J,
        json={"place_id": places[0], "fished_at": "2026-11-01T06:00:00+09:00", "photo_ids": ids},
        headers=device,
    )
    assert res.status_code == 400


def test_post_with_photos_visible_to_others(client, device, places):
    a, b = (
        upload(client, device, purpose="post", color=(1, 2, 3)),
        upload(client, device, purpose="post", color=(4, 5, 6)),
    )
    res = client.post(
        P,
        json={
            "category": "catch",
            "title": "사진 글",
            "body": "본문",
            "species_etc": "쥐노래미",
            "photo_ids": [b["id"], a["id"]],
        },
        headers=device,
    )
    assert res.status_code == 201, res.text
    post = res.json()
    assert [x["id"] for x in post["photos"]] == [b["id"], a["id"]]
    assert post["species_name"] == "쥐노래미" and post["verified"] is False and post["catch"] is None

    other = signup(client)
    listed = client.get(P, headers=other).json()
    mine = next(x for x in listed if x["id"] == post["id"])
    assert mine["photo_count"] == 2 and mine["thumb"]["id"] == b["id"]
    assert client.get(f"/api/v1/photos/{a['id']}", headers=other).status_code == 200

    # 글을 지우면 사진도 볼 수 없다
    client.delete(f"{P}/{post['id']}", headers=device)
    assert client.get(f"/api/v1/photos/{a['id']}", headers=other).status_code == 404


def test_admin_requires_token(client):
    assert client.get("/api/v1/admin/verifications").status_code == 401
    assert client.get("/api/v1/admin/verifications", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert client.get("/api/v1/admin/verifications", headers=ADMIN).status_code == 200
    assert client.get("/api/v1/admin").status_code == 200  # 검토 화면 HTML


def test_precheck_flags_are_reference_only(client, device, places):
    raw = make_jpeg(color=(9, 9, 9), taken="2026:10:20 06:00:00")  # 출조 12일 전 촬영
    ph1 = upload(client, device, data=raw)
    j1 = journal(
        client, device, places[0], species_code="rockfish", photo_ids=[ph1["id"]], request_verification=True
    )
    # 같은 원본을 다른 사람이 다른 기록에 사용
    other = signup(client)
    ph2 = upload(client, other, data=raw)
    j2 = journal(
        client, other, places[0], species_code="rockfish", photo_ids=[ph2["id"]], request_verification=True
    )
    # EXIF 없는 사진
    ph3 = upload(client, other, color=(200, 1, 1))
    journal(
        client, other, places[1], species_code="rockfish", photo_ids=[ph3["id"]], request_verification=True
    )

    items = {i["journal_id"]: i for i in client.get("/api/v1/admin/verifications", headers=ADMIN).json()}
    c1 = items[j1["id"]]["precheck"][0]
    assert c1["time_flag"] is True and "시간" in c1["time_note"]
    c2 = items[j2["id"]]["precheck"][0]
    assert c2["duplicate_journal_ids"] == [j1["id"]] and c2["duplicate_other_user"] is True
    no_exif = [i for i in items.values() if i["photos"] and i["photos"][0]["id"] == ph3["id"]][0]["precheck"][
        0
    ]
    assert "확인 불가" in no_exif["time_note"] and no_exif["time_flag"] is False
    # 참고 정보일 뿐 상태는 그대로 대기
    assert all(i["status"] == "pending" for i in items.values())
    # 관리자는 사진을 볼 수 있다
    assert client.get(f"/api/v1/photos/{ph2['id']}", headers=ADMIN).status_code == 200


def test_share_verified_journal(client, device, places):
    ph = upload(client, device, color=(77, 7, 7))
    j = journal(
        client,
        device,
        places[2],
        species_code="rockfish",
        count=3,
        max_length_cm=33,
        photo_ids=[ph["id"]],
        request_verification=True,
    )
    share = {"category": "question", "title": "오늘 조황", "body": "입질 좋았어요", "journal_id": j["id"]}
    # 승인 전에는 공유 불가
    assert client.post(P, json=share, headers=device).status_code == 400
    client.post(f"/api/v1/admin/verifications/{j['id']}/approve", headers=ADMIN)
    pts = client.get("/api/v1/me/points", headers=device).json()["total_points"]

    res = client.post(P, json=share, headers=device)
    assert res.status_code == 201, res.text
    post = res.json()
    assert post["category"] == "catch" and post["verified"] is True
    assert post["catch"]["count"] == 3 and post["catch"]["max_length_cm"] == 33
    assert [x["id"] for x in post["photos"]] == [ph["id"]]
    # 공유해도 포인트는 그대로 (지급 경로는 일지 하나)
    assert client.get("/api/v1/me/points", headers=device).json()["total_points"] == pts
    # 공유된 인증 사진은 다른 사람도 볼 수 있다
    other = signup(client)
    assert client.get(f"/api/v1/photos/{ph['id']}", headers=other).status_code == 200
    # 같은 기록 중복 공유 불가
    assert client.post(P, json=share, headers=device).status_code == 409
    assert client.get(f"{J}/{j['id']}", headers=device).json()["shared_post_id"] == post["id"]

    # 반려되면 배지·사진이 빠진다
    client.post(
        f"/api/v1/admin/verifications/{j['id']}/reject", json={"reason": "다른 날 사진"}, headers=ADMIN
    )
    again = client.get(f"{P}/{post['id']}", headers=other).json()
    assert again["verified"] is False and again["photos"] == []
    assert client.get(f"/api/v1/photos/{ph['id']}", headers=other).status_code == 404
