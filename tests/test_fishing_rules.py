"""금어기·금지체장 (시행령 별표1·2 요약)"""

import re

from app.routers import fishing_rules

MMDD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def test_endpoint_shape(client):
    fishing_rules._data.cache_clear()
    r = client.get("/api/v1/meta/fishing-rules")
    assert r.status_code == 200 and "max-age" in r.headers["cache-control"]
    d = r.json()
    assert "별표1" in d["source"] and "2026.6.23" in d["source"]
    assert len(d["ban"]) == 33 and len(d["size"]) == 34
    for b in d["ban"]:
        assert b["periods"], b["name"]
        for p in b["periods"]:
            assert MMDD.match(p["from"]) and MMDD.match(p["to"]), b
    names = {b["name"] for b in d["ban"]} | {s["name"] for s in d["size"]}
    for code, law in d["app_species"].items():
        assert set(law) <= names, code  # 앱 어종이 가리키는 법령 이름이 실제로 있다


def test_known_values():
    d = fishing_rules._data()
    ban = {b["name"]: b for b in d["ban"]}
    size = {s["name"]: s for s in d["size"]}
    assert ban["감성돔"]["periods"][0] == {"from": "05-01", "to": "05-31", "region": None, "year": None}
    assert ban["문치가자미"]["periods"][0]["from"] == "12-01"  # 해를 넘김
    assert ban["고등어"]["notice"] and ban["고등어"]["periods"][0]["year"] == 2026  # 해마다 고시
    assert not ban["꽃게"]["notice"] and ban["꽃게"]["periods"][0]["from"] == "06-21"  # 고시 제2024-40호
    assert {f["name"] for f in d["female"]} == {"대게", "붉은대게", "꽃게", "민꽃게"}
    assert size["조피볼락"]["limit"] == "23cm 이하" and size["갈치"]["measure"] == "항문장"


def test_species_seasons(client):
    fishing_rules._seasons.cache_clear()
    d = client.get("/api/v1/meta/species-seasons").json()
    sp = d["species"]
    assert "잘 잡히는 시기" in d["notice"]
    assert sp["black_porgy"]["periods"][0]["months"] == [3, 4, 5, 6, 7]
    assert sp["greenling"]["periods"][1]["months"] == [10, 11, 12, 1]  # 해를 넘김
    assert sp["rockfish"]["kind"] == "birth"
    for code, s in sp.items():
        for p in s["periods"]:
            assert all(1 <= m <= 12 for m in p["months"]) and p["cite"] and p["url"], code


def test_catch_seasons(client):
    fishing_rules._catch.cache_clear()
    d = client.get("/api/v1/meta/catch-seasons").json()
    assert "어업생산동향" in d["source"] and "낚시 조과" in d["notice"]
    hair = d["species"]["hairtail"]["seas"]
    assert set(hair) >= {"서해", "남해"} and all(1 <= m <= 12 for m in hair["서해"]["peak"])
    assert abs(sum(hair["서해"]["share"].values()) - 100) < 1
