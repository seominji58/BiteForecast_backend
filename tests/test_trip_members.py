"""함께 가는 출조계획: 초대·참여·권한·준비물 담당·탈퇴 (확장 기능 설계 1단계)"""

from datetime import timedelta

from app.core.db import SessionLocal
from app.core.timeutil import today_kst
from app.models import TripInvite
from app.models.base import utcnow
from tests.conftest import signup
from tests.test_query_budget import count_queries

URL = "/api/v1/me/trips"
INV = "/api/v1/trip-invites"


def _d(n: int) -> str:
    return str(today_kst() + timedelta(days=n))


def _trip(client, h, places):
    body = {"start_date": _d(3), "end_date": _d(3), "stops": [{"day": _d(3), "place_id": places[0]}]}
    r = client.post(URL, json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _invite(client, h, tid):
    r = client.post(f"{URL}/{tid}/invite", headers=h)
    assert r.status_code == 201, r.text
    return r.json()["code"]


def test_invite_join_and_roles(client, places):
    owner, friend, stranger = signup(client), signup(client), signup(client)
    t = _trip(client, owner, places)
    code = _invite(client, owner, t["id"])
    assert len(code) == 6
    assert _invite(client, owner, t["id"]) == code  # 쓸 수 있는 코드는 다시 만들지 않음

    # 모르는 사람은 계획이 있는지도 모른다
    assert client.get(f"{URL}/{t['id']}", headers=stranger).status_code == 404

    p = client.get(f"{INV}/{code.lower()}", headers=friend).json()  # 소문자로 넣어도 됨
    assert p["trip_id"] == t["id"] and p["member_count"] == 1 and p["already"] is False
    joined = client.post(f"{INV}/{code}/join", headers=friend).json()
    assert joined["my_role"] == "member"
    roles = [(m["role"], m["status"]) for m in joined["members"]]
    assert roles == [("owner", "joined"), ("member", "joined")]
    assert [m["mine"] for m in joined["members"]] == [False, True]

    # 참여자: 보기·해황은 되고, 계획·장소 수정은 안 됨
    assert client.get(f"{URL}/{t['id']}/outlook", headers=friend).status_code == 200
    assert client.patch(f"{URL}/{t['id']}", json={"title": "바꿈"}, headers=friend).status_code == 403
    assert client.delete(f"{URL}/{t['id']}", headers=friend).status_code == 403
    assert client.post(f"{URL}/{t['id']}/invite", headers=friend).status_code == 403

    # 목록: 참여자에게도 보이고, 함께 가는 사람 수
    lst = client.get(URL, headers=friend).json()
    item = next(x for x in lst if x["id"] == t["id"])
    assert item["my_role"] == "member" and item["member_count"] == 2
    owner_item = next(x for x in client.get(URL, headers=owner).json() if x["id"] == t["id"])
    assert owner_item["my_role"] == "owner" and owner_item["member_count"] == 2

    # 만든 사람이 다시 참여해도 그대로
    assert client.post(f"{INV}/{code}/join", headers=owner).json()["my_role"] == "owner"


def test_checklist_assignment_rules(client, places):
    owner, friend = signup(client), signup(client)
    t = _trip(client, owner, places)
    client.post(f"{INV}/{_invite(client, owner, t['id'])}/join", headers=friend)
    me = client.get(f"{URL}/{t['id']}", headers=friend).json()
    fid = next(m["user_id"] for m in me["members"] if m["mine"])
    oid = next(m["user_id"] for m in me["members"] if m["role"] == "owner")
    item = me["checklist"][0]["id"]
    path = f"{URL}/{t['id']}/checklist/{item}"

    # 참여자: 자기 자신만 담당, 체크 가능
    r = client.patch(path, json={"assignee_user_id": fid, "checked": True}, headers=friend).json()
    c = next(x for x in r["checklist"] if x["id"] == item)
    assert c["assignee_user_id"] == fid and c["checked"] is True and c["assignee_nickname"]
    assert client.patch(path, json={"assignee_user_id": oid}, headers=friend).status_code == 403
    # 만든 사람은 누구에게나, 함께 가지 않는 사람은 안 됨
    stranger = signup(client)
    sid = _trip(client, stranger, places)["members"][0]["user_id"]  # 자기 계획에서 자기 user_id
    assert client.patch(path, json={"assignee_user_id": sid}, headers=owner).status_code == 400
    r = client.patch(path, json={"assignee_user_id": oid}, headers=owner).json()
    assert next(x for x in r["checklist"] if x["id"] == item)["assignee_user_id"] == oid
    # 참여자는 다른 사람 담당을 내려놓을 수 없다
    assert client.patch(path, json={"assignee_user_id": None}, headers=friend).status_code == 403

    # 통째 바꾸기에서도 담당자는 함께 가는 사람만, 담당이 유지된다
    items = [{"label": "아이스박스", "assignee_user_id": fid}, {"label": "밑밥"}]
    r = client.put(f"{URL}/{t['id']}/checklist", json=items, headers=owner).json()
    assert [x["assignee_user_id"] for x in r["checklist"]] == [fid, None]
    bad = [{"label": "x", "assignee_user_id": sid}]
    assert client.put(f"{URL}/{t['id']}/checklist", json=bad, headers=owner).status_code == 400


def test_status_leave_and_remove(client, places):
    owner, a, b = signup(client), signup(client), signup(client)
    t = _trip(client, owner, places)
    code = _invite(client, owner, t["id"])
    client.post(f"{INV}/{code}/join", headers=a)
    client.post(f"{INV}/{code}/join", headers=b)
    aid = next(m["user_id"] for m in client.get(f"{URL}/{t['id']}", headers=a).json()["members"] if m["mine"])
    item = client.get(f"{URL}/{t['id']}", headers=a).json()["checklist"][0]["id"]
    client.patch(f"{URL}/{t['id']}/checklist/{item}", json={"assignee_user_id": aid}, headers=a)

    # 미정 → 목록에 남음, 불참 → 목록에서 빠지고 담당 내려놓음
    assert client.patch(f"{URL}/{t['id']}/members/me", json={"status": "maybe"}, headers=a).status_code == 200
    assert any(x["id"] == t["id"] for x in client.get(URL, headers=a).json())
    r = client.patch(f"{URL}/{t['id']}/members/me", json={"status": "declined"}, headers=a).json()
    assert r["checklist"][0]["assignee_user_id"] is None
    assert not any(x["id"] == t["id"] for x in client.get(URL, headers=a).json())
    # 만든 사람은 참여 상태가 없다
    me_path = f"{URL}/{t['id']}/members/me"
    assert client.patch(me_path, json={"status": "maybe"}, headers=owner).status_code == 400

    b_view = client.get(f"{URL}/{t['id']}", headers=b).json()
    bid = next(m["user_id"] for m in b_view["members"] if m["mine"])
    # 참여자는 다른 사람을 내보낼 수 없고, 스스로는 나갈 수 있다
    assert client.delete(f"{URL}/{t['id']}/members/{aid}", headers=b).status_code == 403
    assert client.delete(f"{URL}/{t['id']}/members/{bid}", headers=b).status_code == 204
    assert client.get(f"{URL}/{t['id']}", headers=b).status_code == 404
    # 만든 사람은 내보낼 수 있다
    assert client.delete(f"{URL}/{t['id']}/members/{aid}", headers=owner).status_code == 204
    assert [m["role"] for m in client.get(f"{URL}/{t['id']}", headers=owner).json()["members"]] == ["owner"]


def test_invite_expire_and_revoke(client, places):
    owner, friend = signup(client), signup(client)
    t = _trip(client, owner, places)
    code = _invite(client, owner, t["id"])
    assert client.delete(f"{URL}/{t['id']}/invite", headers=owner).status_code == 204
    assert client.get(f"{INV}/{code}", headers=friend).status_code == 404
    assert client.post(f"{INV}/{code}/join", headers=friend).status_code == 404

    code2 = _invite(client, owner, t["id"])
    assert code2 != code
    with SessionLocal() as db:
        inv = db.query(TripInvite).filter(TripInvite.code == code2).one()
        inv.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert client.post(f"{INV}/{code2}/join", headers=friend).status_code == 404
    assert client.get(f"{INV}/{code2}").status_code == 401  # 로그인 필요


def test_member_can_record_at_trip_stop(client, places):
    owner, friend = signup(client), signup(client)
    t = _trip(client, owner, places)
    client.post(f"{INV}/{_invite(client, owner, t['id'])}/join", headers=friend)
    stop = t["stops"][0]["id"]
    body = {"place_id": places[0], "fished_at": "2026-11-01T06:00:00+09:00", "trip_stop_id": stop}
    assert client.post("/api/v1/journals", json=body, headers=friend).status_code == 201
    # 함께 가지 않는 사람은 연결할 수 없다
    assert client.post("/api/v1/journals", json=body, headers=signup(client)).status_code == 400
    # 계획 장소에 참여자의 기록도 모인다
    stops = client.get(f"{URL}/{t['id']}", headers=owner).json()["stops"]
    assert len(stops[0]["journal_ids"]) == 1


def test_account_deletion_cleans_membership(client, places):
    owner, friend = signup(client), signup(client)
    t = _trip(client, owner, places)
    client.post(f"{INV}/{_invite(client, owner, t['id'])}/join", headers=friend)
    me = client.get(f"{URL}/{t['id']}", headers=friend).json()
    fid = next(m["user_id"] for m in me["members"] if m["mine"])
    item = me["checklist"][0]["id"]
    client.patch(f"{URL}/{t['id']}/checklist/{item}", json={"assignee_user_id": fid}, headers=friend)
    assert client.delete("/api/v1/me/account", headers=friend).status_code == 204
    after = client.get(f"{URL}/{t['id']}", headers=owner).json()
    assert [m["role"] for m in after["members"]] == ["owner"]
    assert after["checklist"][0]["assignee_user_id"] is None
    # 만든 사람이 탈퇴하면 계획·참여자·초대 코드가 함께 지워진다
    other = signup(client)
    t2 = _trip(client, owner, places)
    code = _invite(client, owner, t2["id"])
    client.post(f"{INV}/{code}/join", headers=other)
    assert client.delete("/api/v1/me/account", headers=owner).status_code == 204
    assert client.get(f"{URL}/{t2['id']}", headers=other).status_code == 404
    assert not any(x["id"] == t2["id"] for x in client.get(URL, headers=other).json())


def test_trip_list_does_not_scale_with_members(client, places):
    owner = signup(client)
    t = _trip(client, owner, places)
    code = _invite(client, owner, t["id"])
    client.post(f"{INV}/{code}/join", headers=signup(client))
    with count_queries() as one:
        client.get(URL, headers=owner)
        client.get(f"{URL}/{t['id']}", headers=owner)
    for _ in range(4):
        client.post(f"{INV}/{code}/join", headers=signup(client))
    with count_queries() as five:
        client.get(URL, headers=owner)
        client.get(f"{URL}/{t['id']}", headers=owner)
    assert five[0] <= one[0] + 2, (one[0], five[0])
