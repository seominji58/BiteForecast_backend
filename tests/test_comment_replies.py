"""대댓글: 원댓글에만 한 단계 · 다른 글·지운 댓글에는 못 단다 · 원댓글이 지워져도 답글은 남는다"""

from tests.conftest import signup

URL = "/api/v1/community"


def _post(client, h):
    body = {"category": "free", "title": "대댓글 테스트", "body": "본문"}
    r = client.post(f"{URL}/posts", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _comment(client, h, post_id, body, parent_id=None):
    payload = {"body": body} if parent_id is None else {"body": body, "parent_id": parent_id}
    return client.post(f"{URL}/posts/{post_id}/comments", json=payload, headers=h)


def test_reply_one_level(client):
    a, b = signup(client), signup(client)
    pid = _post(client, a)
    root = _comment(client, a, pid, "원댓글").json()["comments"][0]
    assert root["parent_id"] is None and root["deleted"] is False

    r = _comment(client, b, pid, "답글", parent_id=root["id"])
    assert r.status_code == 201, r.text
    comments = r.json()["comments"]
    reply = next(c for c in comments if c["body"] == "답글")
    assert reply["parent_id"] == root["id"]
    # 댓글 수에는 답글도 들어간다
    assert r.json()["comment_count"] == 2

    # 답글에 다시 답글은 안 된다
    assert _comment(client, a, pid, "답글의 답글", parent_id=reply["id"]).status_code == 400


def test_reply_parent_must_be_same_post_and_alive(client):
    a = signup(client)
    p1, p2 = _post(client, a), _post(client, a)
    root = _comment(client, a, p1, "원댓글").json()["comments"][0]
    assert _comment(client, a, p2, "다른 글", parent_id=root["id"]).status_code == 404
    assert _comment(client, a, p1, "없는 댓글", parent_id=999999).status_code == 404

    assert client.delete(f"{URL}/comments/{root['id']}", headers=a).status_code == 204
    assert _comment(client, a, p1, "지운 댓글에 답글", parent_id=root["id"]).status_code == 404


def test_deleted_parent_keeps_replies_with_placeholder(client):
    a, b = signup(client), signup(client)
    pid = _post(client, a)
    root = _comment(client, a, pid, "곧 지울 원댓글").json()["comments"][0]
    _comment(client, b, pid, "남는 답글", parent_id=root["id"])
    assert client.delete(f"{URL}/comments/{root['id']}", headers=a).status_code == 204

    detail = client.get(f"{URL}/posts/{pid}", headers=b).json()
    ph = next(c for c in detail["comments"] if c["id"] == root["id"])
    assert ph["deleted"] is True and ph["body"] == "" and ph["author"]["nickname"] == ""
    reply = next(c for c in detail["comments"] if c["body"] == "남는 답글")
    assert reply["parent_id"] == root["id"]
    # 자리표시는 댓글 수에 넣지 않는다
    assert detail["comment_count"] == 1


def test_old_clients_without_parent_still_work(client):
    a = signup(client)
    pid = _post(client, a)
    r = client.post(f"{URL}/posts/{pid}/comments", json={"body": "예전 앱"}, headers=a)
    assert r.status_code == 201 and r.json()["comments"][0]["parent_id"] is None
