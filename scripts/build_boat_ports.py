"""낚시어선 출항항 (해양수산부 낚시 어선업 신고정보 API) → seeds/fishing_boat_ports.json (2026-11-23).

- 원자료: 06_개발환경/data_raw/해양수산부_낚시어선업신고정보_<날짜>.json (API 전체 4,809척 저장본)
- 영업기간(bsnStEndDt)이 기준일에 유효한 배만 센다
- 출항항(shpmHangNm)은 자유 입력이라 형식이 제각각 → 「○○항·포구·선착장·물양장·부두」 이름을 뽑아
  신고 시군(fshNtNm 앞부분)과 함께 카카오에서 「항구」를 찾는다. 시군이 주소에 없으면 버린다
- 항 이름이 없는 신고(「인천광역시 중구」처럼 시군만)는 시군 합계에만 넣는다
- 연락처는 원자료에 없다. 배 이름·톤수·최대 승객 수만 둔다

실행: .venv/bin/python -m scripts.build_boat_ports [기준일 YYYY-MM-DD]
"""

import json
import re
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import httpx

from app.core.config import get_settings

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT.parent / "06_개발환경" / "data_raw"
OUT = ROOT / "seeds" / "fishing_boat_ports.json"
PORT = re.compile(r"([가-힣0-9]+(?:항|포구|선착장|물양장|부두))")
NOT_PORT = {"포항"}  # 「포항시」에서 잘못 뽑힘. 포항의 실제 항은 「구룡포항」 등으로 따로 나온다


def _valid(b: dict, today: date) -> bool:
    try:
        a, z = (date(*map(int, s.strip().split("."))) for s in b["bsnStEndDt"].split("~"))
        return a <= today <= z
    except (KeyError, ValueError, AttributeError):
        return False


def _sgg(b: dict) -> str:
    return re.sub(r"\s*제\s*\d.*", "", b.get("fshNtNm") or "").strip()


PROVINCE = {
    "강원": "강원",
    "경기": "경기",
    "경상남도": "경남",
    "경상북도": "경북",
    "전라남도": "전남",
    "전남광주": "전남",
    "전라북도": "전북",
    "전북특별": "전북",
    "충청남도": "충남",
    "충청북도": "충북",
    "제주": "제주",
    "부산": "부산",
    "인천": "인천",
    "울산": "울산",
}


def _regions(sgg: str) -> tuple[str | None, list[str]]:
    """(도 약칭, 시·군·구 이름들). 「경상남도 거제시」 → ("경남", ["거제"])"""
    parts = sgg.split()
    prov = next((v for k, v in PROVINCE.items() if parts and parts[0].startswith(k)), None)
    towns = [w[:-1] for w in parts if len(w) > 1 and w.endswith(("시", "군", "구"))]
    return prov, towns


def _find(http: httpx.Client, sgg: str, name: str) -> dict | None:
    """신고 시군 안에서 그 항을 찾는다. 같은 도의 「항구」 분류도 받아준다 (다른 시군 항에서 출항하는 배)"""
    prov, towns = _regions(sgg)
    stem = name[:-1] if name.endswith("항") else name
    queries = [f"{t} {name}" for t in towns] + [name] + [f"{t} {stem}" for t in towns]
    for q in queries:
        docs = (
            http.get("https://dapi.kakao.com/v2/local/search/keyword.json", params={"query": q, "size": 10})
            .json()
            .get("documents", [])
        )
        time.sleep(0.03)
        same_town = [d for d in docs if any(t in d.get("address_name", "") for t in towns)]
        harbor = [
            d
            for d in docs
            if "항구" in d.get("category_name", "")
            and stem in d["place_name"]
            and (
                not prov
                or d.get("address_name", "").startswith(prov)
                or prov in d.get("address_name", "")[:6]
            )
        ]
        for pool in (
            [d for d in same_town if "항구" in d.get("category_name", "")],
            [d for d in same_town if stem in d["place_name"]],
            harbor,
        ):
            if pool:
                return pool[0]
    return None


def main() -> None:
    today = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    src = sorted(RAW.glob("해양수산부_낚시어선업신고정보_*.json"))[-1]
    boats = [b for b in json.loads(src.read_text(encoding="utf-8")) if _valid(b, today)]
    key = get_settings().kakao_rest_key
    http = httpx.Client(headers={"Authorization": f"KakaoAK {key}"}, timeout=10)

    by_port: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_sgg: dict[str, int] = defaultdict(int)
    for b in boats:
        sgg = _sgg(b)
        by_sgg[sgg] += 1
        names = [n for n in PORT.findall(b.get("shpmHangNm") or "") if n not in NOT_PORT]
        if names:
            by_port[(sgg, names[-1])].append(b)

    ports, missed = [], []
    for (sgg, name), bs in sorted(by_port.items()):
        hit = _find(http, sgg, name)
        if not hit:
            missed.append(f"{sgg} {name} ({len(bs)})")
            continue
        ports.append(
            {
                "name": name,
                "sgg": sgg,
                "lat": round(float(hit["y"]), 5),
                "lon": round(float(hit["x"]), 5),
                "kakao_name": hit["place_name"],
                "kakao_url": hit.get("place_url"),
                "boats": len(bs),
                "max_passengers": max(int(re.sub(r"\D", "", b.get("maxPsrNum") or "0") or 0) for b in bs),
                "boat_names": sorted({b["fsboNm"] for b in bs if b.get("fsboNm")})[:30],
            }
        )
    # 같은 카카오 항구로 모인 것은 합친다
    # (시군 이름이 바뀐 신고: 「전라남도 여수시」·「전남광주통합특별시 여수시」 등)
    merged: dict[tuple, dict] = {}
    for p in ports:
        k = (p["kakao_name"], round(p["lat"], 3), round(p["lon"], 3))
        if k in merged:
            m = merged[k]
            m["boats"] += p["boats"]
            m["max_passengers"] = max(m["max_passengers"], p["max_passengers"])
            m["boat_names"] = sorted(set(m["boat_names"]) | set(p["boat_names"]))[:30]
            m["reported_as"] = sorted(set(m["reported_as"]) | {p["name"]})
        else:
            merged[k] = {**p, "reported_as": [p["name"]]}
    ports = sorted(merged.values(), key=lambda p: -p["boats"])
    OUT.write_text(
        json.dumps(
            {
                "_note": "scripts/build_boat_ports.py 로 생성 — 직접 고치지 말 것",
                "source": f"해양수산부 낚시 어선업 신고정보 ({src.stem.split('_')[-1]} 받음)",
                "as_of": today.isoformat(),
                "boats_total": len(boats),
                "boats_on_map": sum(p["boats"] for p in ports),
                "ports": ports,
                "by_sgg": dict(sorted(by_sgg.items())),
                "unmatched": missed,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    on_map = sum(p["boats"] for p in ports)
    print(f"영업 중 {len(boats)}척 · 항구 {len(ports)}곳에 {on_map}척 · 못 찾은 항 {len(missed)}")
    print(missed[:30])


if __name__ == "__main__":
    main()
