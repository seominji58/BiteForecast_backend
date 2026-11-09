"""낚시터 주소 ↔ 원본 좌표 대조 (읽기 전용 — DB 를 바꾸지 않는다).

보고서: docs/03_데이터/2026-11-10_주소API_좌표대조_보고서.md
입력: 좌표 품질 감사 CSV (scripts/audit_coordinates.py 출력 — 원본 도로명·지번 주소·원문 좌표 포함)
출력: 낚시터 한 곳 = 한 줄 CSV

원칙
- 원본 좌표는 바꾸지 않는다. 등급도 바꾸지 않는다 (변경 「후보」만 적는다)
- VWorld 지오코더 결과 좌표는 저장하지 않는다 (VWorld: 「별도의 저장장치나 DB에 저장할 수 없습니다」).
  메모리에서 원본 좌표와의 거리만 계산하고, CSV 에는 상태·일치 여부·거리(파생값)만 남긴다
- 행정안전부 도로명주소 검색 API: 결과가 여러 개면 임의로 고르지 않는다 (「다중 결과」)
- 인증키는 backend/.env 에서만 읽고, 키가 들어간 URL·응답 원문을 출력하지 않는다

사용: python scripts/verify_addresses.py <감사.csv> <출력.csv> [--limit N] [--ids 177,130] [--public]
  --public: VWorld 결과에서 계산한 거리 값을 뺀다 (VWorld 약관상 파생값 저장 허용 여부가 확인될 때까지)
"""

import argparse
import csv
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

JUSO_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"
VWORLD_URL = "https://api.vworld.kr/req/address"

# 새 광역 행정구역 이름 → 주소 DB 가 아직 모를 수 있는 기존 이름 (조회 실패 시 한 번 더 시도, 결과에 표시)
LEGACY_SIDO = {"전남광주통합특별시": "전라남도"}

OFFSHORE = re.compile(r"(부유|좌대|가두리|수상|해상|바지|잔교|고정형)")


def load_env() -> dict[str, str]:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def km(a, b) -> float:
    r = math.pi / 180
    h = (
        math.sin((b[0] - a[0]) * r / 2) ** 2
        + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin((b[1] - a[1]) * r / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def http_json(url: str) -> tuple[str, dict | None]:
    """(오류 종류, JSON). 키가 든 URL·응답 원문은 돌려주지 않는다"""
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return "", json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}", None
    except Exception as e:  # noqa: BLE001 — 네트워크·형식 오류를 상태로만 기록
        return type(e).__name__, None


# --- 주소 정리 ---


def clean_road(a: str) -> str:
    """도로명 주소에서 상호·층·괄호 설명을 뗀다 (예: 「…복룡로 688-6, 복룡횟집」 → 「…복룡로 688-6」)"""
    a = a.split(",")[0]
    a = re.sub(r"\(.*?\)", "", a)
    a = re.sub(r"\s\d+층.*$", "", a)
    return re.sub(r"\s+", " ", a).strip()


def clean_jibun(a: str) -> tuple[str, bool]:
    """지번 주소에서 「지선」·뒤 설명을 뗀다. (주소, 지선 여부)"""
    jisun = "지선" in a
    a = a.replace("지선", " ")
    a = re.sub(r"\(.*?\)", "", a)
    m = re.match(r"(.*?\S+(?:리|동|가|로)\s+(?:산\s*)?\d+(?:-\d+)?)", a)
    a = m.group(1) if m else a
    return re.sub(r"\s+", " ", a).strip(), jisun


def tokens(a: str) -> list[str]:
    # 「산 14-6」과 「산14-6」을 같게 본다 (띄어쓰기 차이). 「산」이 빠진 번지는 다른 필지로 본다
    a = re.sub(r"(^|\s)산\s+(\d)", r"\1산\2", a.strip())
    return [t for t in re.split(r"\s+", a) if t]


def same_address(query: str, refined: str) -> tuple[bool, str]:
    """시군구·읍면동(또는 도로명)·번지가 같은지. 다르면 무엇이 다른지"""
    q = tokens(query)
    r = tokens(refined)
    if not q or not r:
        return False, "비교 불가"
    num = re.compile(r"^(산\s*)?\d+(-\d+)?$")
    qn = [t for t in q if num.match(t)]
    rn = [t for t in r if num.match(t)]
    q_words = [t for t in q if not num.match(t)][1:]  # 시·도 이름은 표기가 달라 비교하지 않는다
    r_words = set(t for t in r if not num.match(t))
    missing = [t for t in q_words if t not in r_words]
    if missing:
        return False, f"행정구역·도로명 다름({' '.join(missing)})"
    if qn and rn and qn[-1] != rn[-1]:
        return False, "번지 다름"  # 정제 주소(응답)의 번지는 기록하지 않는다
    return True, ""


# --- API ---


class Juso:
    def __init__(self, key: str):
        self.key = key
        self.disabled = "" if key else "키 없음"

    def search(self, keyword: str) -> dict:
        if self.disabled:
            return {"status": "검색 실패", "detail": self.disabled}
        url = (
            JUSO_URL
            + "?"
            + urllib.parse.urlencode(
                {
                    "confmKey": self.key,
                    "currentPage": 1,
                    "countPerPage": 10,
                    "keyword": keyword,
                    "resultType": "json",
                }
            )
        )
        err, d = http_json(url)
        time.sleep(0.6)  # 호출 간격
        if err or d is None:
            return {"status": "검색 실패", "detail": err or "응답 없음"}
        common = d["results"]["common"]
        if common.get("errorCode") != "0":
            if common.get("errorCode") == "E0001":
                self.disabled = f"키 미승인({common['errorCode']})"  # 같은 오류로 계속 부르지 않는다
            return {
                "status": "검색 실패",
                "detail": f"{common.get('errorCode')} {common.get('errorMessage')}",
            }
        items = d["results"].get("juso") or []
        if not items:
            return {"status": "결과 없음", "detail": ""}
        exact = [
            x
            for x in items
            if same_address(keyword, x["roadAddr"])[0] or same_address(keyword, x["jibunAddr"])[0]
        ]
        if len(exact) == 1:
            x = exact[0]
            return {
                "status": "검색됨",
                "detail": "",
                "road": x["roadAddr"],
                "jibun": x["jibunAddr"],
                "n": len(items),
            }
        if len(items) > 1 or len(exact) > 1:
            return {
                "status": "다중 결과",
                "detail": f"{common.get('totalCount')}건 — 임의 선택 안 함",
                "n": len(items),
            }
        x = items[0]
        return {
            "status": "주소 불일치",
            "detail": "검색 결과가 원본과 다름",
            "road": x["roadAddr"],
            "jibun": x["jibunAddr"],
        }


class VWorld:
    def __init__(self, key: str):
        self.key = key

    def geocode(self, address: str, kind: str) -> dict:
        """kind: road | parcel. 좌표는 돌려주지만 저장하지 않는다 (호출한 쪽에서 거리만 계산)"""
        if not self.key:
            return {"status": "검색 실패", "detail": "키 없음"}
        url = (
            VWORLD_URL
            + "?"
            + urllib.parse.urlencode(
                {
                    "service": "address",
                    "request": "getcoord",
                    "version": "2.0",
                    "crs": "epsg:4326",
                    "address": address,
                    "refine": "true",
                    "simple": "false",
                    "format": "json",
                    "type": kind,
                    "key": self.key,
                }
            )
        )
        err, d = http_json(url)
        time.sleep(0.25)
        if err or d is None:
            return {"status": "검색 실패", "detail": err or "응답 없음"}
        r = d.get("response") or {}
        st = r.get("status")
        if st == "NOT_FOUND":
            return {"status": "결과 없음", "detail": ""}
        if st != "OK":
            return {"status": "검색 실패", "detail": (r.get("error") or {}).get("code", st or "오류")}
        refined = (r.get("refined") or {}).get("text") or ""
        p = (r.get("result") or {}).get("point") or {}
        try:
            pt = (float(p["y"]), float(p["x"]))
        except (KeyError, TypeError, ValueError):
            return {"status": "검색 실패", "detail": "좌표 없음"}
        ok, why = same_address(address, refined)
        return {"status": "검색됨" if ok else "주소 불일치", "detail": why, "refined": refined, "_pt": pt}

    def where(self, pt: tuple[float, float]) -> dict:
        """좌표가 속한 시·군 (역지오코딩). 행정구역 이름은 비교에만 쓰고 저장하지 않는다"""
        if not self.key:
            return {"status": "검색 실패"}
        url = (
            VWORLD_URL
            + "?"
            + urllib.parse.urlencode(
                {
                    "service": "address",
                    "request": "getaddress",
                    "version": "2.0",
                    "crs": "epsg:4326",
                    "point": f"{pt[1]},{pt[0]}",
                    "type": "parcel",
                    "format": "json",
                    "simple": "false",
                    "key": self.key,
                }
            )
        )
        err, d = http_json(url)
        time.sleep(0.25)
        if err or d is None:
            return {"status": "검색 실패"}
        r = d.get("response") or {}
        if r.get("status") == "NOT_FOUND":
            return {"status": "바다"}  # 지번이 없는 곳 = 바다 위(또는 미등록 토지)
        if r.get("status") != "OK":
            return {"status": "검색 실패"}
        st = ((r.get("result") or [{}])[0].get("structure")) or {}
        return {"status": "OK", "_sgg": f"{st.get('level1', '')} {st.get('level2', '')}".strip()}


def sgg_of(addr: str) -> str:
    """주소의 시·군·구 (시·도 이름 표기 차이는 무시)"""
    t = tokens(addr)
    return (
        " ".join(t[1:3]) if len(t) >= 3 and re.search(r"(시|군|구)$", t[2]) else (t[1] if len(t) > 1 else "")
    )


def band(d: float | None) -> str:
    if d is None:
        return ""
    if d <= 0.3:
        return "주소지와 일치(≤0.3km)"
    if d <= 3:
        return "주소지 부근(0.3~3km)"
    if d <= 10:
        return "주소지와 떨어짐(3~10km)"
    return "주소지와 크게 다름(>10km)"


def judge(r: dict, d: float | None, jisun: bool, coord_area: str) -> tuple[str, str, str]:
    """(위치 유형 추정, 등급 변경 후보, 추가 확인). 모두 「추정」 — 공식 확인 아님.
    coord_area: 원본 좌표가 있는 곳 — 같은 시군 / 다른 시군 / 바다 / 확인 못 함 / (가까워서 안 봄)"""
    offshore = bool(OFFSHORE.search(r.get("수상시설물유형", "") + r["낚시터"]))
    grade = r["등급"]
    if d is None:
        return "위치 유형 확인 불가(주소 대조 안 됨)", "유지", "주소로 대조할 수 없음 — 지자체·업체 확인"
    if d > 3:
        if coord_area == "다른 시군":
            cand = "유지(D)" if grade == "D" else "D 후보"
            return "원본 좌표가 주소와 다른 시·군 — 오류 가능성 높음", cand, "원본 좌표 출처 확인 — 지자체"
        if coord_area == "바다" and offshore:
            return (
                "주소지(사업장)와 떨어진 바다 위 좌표 — 실제 해상 위치일 수도, 오류일 수도 있음(구분 불가)",
                "유지(C) · 우선 확인",
                "이 좌표가 실제 좌대인지 지자체·업체 확인",
            )
        return (
            f"주소지와 3km 넘게 떨어진 {'같은 시·군' if coord_area == '같은 시군' else '곳'} — 원인 불명",
            "유지(C) · 우선 확인" if grade != "D" else "유지(D)",
            "좌표가 무엇의 위치인지 확인",
        )
    if d <= 0.3:
        if offshore:
            return (
                "사업장·대표 주소 좌표(추정) — 해상 시설이면 실제 낚시 위치 아님",
                "유지(C)",
                "실제 좌대 위치 확인 필요",
            )
        return "주소지 좌표(추정)", "B 후보(대표 위치 확인 — 행안부 대조 후)", "실제 낚시 위치인지 확인"
    if jisun or offshore:
        return (
            "주소지 앞 해상 위치일 가능성(추정)",
            "유지(C)",
            "실제 좌대가 이 좌표인지 확인 (지선 주소 = 육상 기준점)",
        )
    return "주소지 부근 다른 위치(추정)", "유지(C)", "사업장 위치와 낚시 위치 구분 확인"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audit_csv")
    ap.add_argument("out_csv")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="")
    ap.add_argument(
        "--public",
        action="store_true",
        help="저장소에 올릴 판: VWorld 좌표에서 계산한 거리(km·구간)를 빼고 상태·판정만 남긴다",
    )
    a = ap.parse_args()

    env = load_env()
    juso = Juso(env.get("JUSO_SEARCH_KEY", ""))
    vw = VWorld(env.get("VWORLD_API_KEY", ""))
    rows = list(csv.DictReader(open(a.audit_csv, encoding="utf-8-sig")))
    if a.ids:
        want = {x.strip() for x in a.ids.split(",")}
        rows = [r for r in rows if r["id"] in want]

    def priority(r) -> int:
        if r["등급"] == "D":
            return 1
        if r["우선검토 사유"] or r["같은좌표·같은주소"]:
            return 2
        if r["출처구분"] == "공공데이터 표준":
            return 3
        return 4

    rows.sort(key=lambda r: (priority(r), int(r["id"])))
    if a.limit:
        rows = rows[: a.limit]

    out = []
    for i, r in enumerate(rows, 1):
        pri = priority(r)
        base = {
            "id": r["id"],
            "낚시터": r["낚시터"],
            "출처구분": r["출처구분"],
            "우선순위": pri,
            "기존등급": r["등급"],
            "기존세부": r["세부"],
            "수상시설물유형": r["수상시설물유형"],
        }
        if r["출처구분"] != "공공데이터 표준":
            why = (
                "기관 지정 해상 지점 — 주소가 없어 주소 대조 대상 아님. 주변과 떨어져 있어도 오류로 보지 않음"
                if r["출처구분"] == "국립해양조사원 지점"
                else "수동 지정 항구·해변 — 주소 없음, 주소 대조 대상 아님"
            )
            out.append({**base, "대조상태": "대상 아님", "비고": why, "기존등급 변경 후보": "유지"})
            continue
        orig = (float(r["위도(원문)"]), float(r["경도(원문)"]))
        road = clean_road(r["도로명주소(원본)"]) if r["도로명주소(원본)"] else ""
        jibun, jisun = clean_jibun(r["지번주소(원본)"] or (r["주소(DB)"] if "지선" in r["주소(DB)"] else ""))

        def try_vw(addr, kind):
            res = vw.geocode(addr, kind)
            note = ""
            if res["status"] in ("결과 없음", "주소 불일치", "검색 실패"):
                for new, old in LEGACY_SIDO.items():
                    if addr.startswith(new):
                        res2 = vw.geocode(addr.replace(new, old, 1), kind)
                        if res2["status"] == "검색됨":
                            res, note = res2, f"시·도 이름 「{new}」→「{old}」로 조회"
            return res, note

        v_road, n1 = try_vw(road, "road") if road else ({"status": "주소 없음", "detail": ""}, "")
        v_par, n2 = try_vw(jibun, "parcel") if jibun else ({"status": "주소 없음", "detail": ""}, "")
        j = juso.search(road or jibun) if (road or jibun) else {"status": "주소 없음", "detail": ""}

        d_road = (
            round(km(orig, v_road["_pt"]), 2) if "_pt" in v_road and v_road["status"] == "검색됨" else None
        )
        d_par = round(km(orig, v_par["_pt"]), 2) if "_pt" in v_par and v_par["status"] == "검색됨" else None
        # 도로명·지번 두 결과가 서로 얼마나 떨어졌는지 (주소 데이터 자체의 불일치)
        d_rp = round(km(v_road["_pt"], v_par["_pt"]), 2) if d_road is not None and d_par is not None else None
        d = d_par if (jisun and d_par is not None) else (d_road if d_road is not None else d_par)

        if d is not None:
            state = "대조 완료"
        elif r["등급"] == "D" and not (road or jibun):
            state = "위치 확인 불가"
        else:
            sts = {v_road["status"], v_par["status"]} - {"주소 없음"}
            state = (
                "주소 불일치"
                if "주소 불일치" in sts
                else "결과 없음"
                if "결과 없음" in sts
                else "검색 실패"
                if sts
                else "위치 확인 불가"
            )
        coord_area = "가까움(확인 안 함)"
        if d is not None and d > 3:
            w = vw.where(orig)
            if w["status"] == "바다":
                coord_area = "바다"
            elif w["status"] == "OK":
                addr_sgg = sgg_of(road or jibun).split()[-1]
                coord_area = "같은 시군" if addr_sgg and addr_sgg in w["_sgg"] else "다른 시군"
            else:
                coord_area = "확인 못 함"
        no_lot = bool(jibun) and not re.search(r"\d", jibun)
        port_only = no_lot and bool(re.search(r"(항|해상)$", jibun.split()[-1]))
        loc, cand, todo = judge(r, d, jisun, coord_area)
        if port_only and d is None:
            state = "주소 검색 불가"
            loc = "위치 유형 확인 불가 — 주소가 항구·해상 이름뿐(번지 없음)"
            todo = "항구 이름만 있어 주소로 대조할 수 없음 — 지자체 신고서 위치도 확인"
        elif no_lot:
            todo = "주소에 번지 없음(리 단위로만 조회) · " + todo
        if "폐업" in r["낚시터"]:
            todo = "이름에 「폐업」 표기 — 운영 여부 확인 · " + todo
        if r["등급"] == "D" and cand.startswith("유지"):
            cand = "유지(D)"
        out.append(
            {
                **base,
                "조회 도로명": road,
                "조회 지번": jibun + (" (지선)" if jisun else ""),
                "VWorld 도로명 상태": v_road["status"]
                + (f" · {v_road['detail']}" if v_road.get("detail") else ""),
                "VWorld 지번 상태": v_par["status"]
                + (f" · {v_par['detail']}" if v_par.get("detail") else ""),
                "행안부 검색 상태": j["status"] + (f" · {j['detail']}" if j.get("detail") else ""),
                "원본↔도로명주소 km": d_road,
                "원본↔지번주소 km": d_par,
                "도로명↔지번 주소 간 km": d_rp,
                "판정 거리 km": d,
                "원본 좌표 위치": coord_area,
                "거리 구간": band(d),
                "대조상태": state,
                "위치 유형(추정)": loc,
                "기존등급 변경 후보": cand,
                "추가 확인": todo,
                "비고": " · ".join(x for x in (n1, n2) if x),
            }
        )
        if i % 20 == 0:
            print(f"  {i}/{len(rows)}", flush=True)

    if a.public:
        derived = (
            "원본↔도로명주소 km",
            "원본↔지번주소 km",
            "도로명↔지번 주소 간 km",
            "판정 거리 km",
            "거리 구간",
        )
        out = [{k: v for k, v in o.items() if k not in derived} for o in out]
    keys = []
    for o in out:
        for k in o:
            if k not in keys:
                keys.append(k)
    with open(a.out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(out)
    print(f"완료 {len(out)}곳 · 행안부 검색: {juso.disabled or '사용'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
