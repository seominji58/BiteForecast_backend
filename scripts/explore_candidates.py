# ruff: noqa: E501 — 문서(마크다운) 문장을 그대로 만드는 스크립트라 긴 줄을 허용한다
"""탐험 30선 후보 뽑기 (탐험 2단계, 2026-11-19) — 개정 기준(확장_기능_설계.md 2장)에 맞춰 자동으로 거를 수 있는 것만 거른다.

자동으로 하는 것
- 해수부 갯바위낚시포인트(참고 포인트 1,070곳) 중 이름에 방파제·항·선창·포구·해변·해수욕장·등대·선착장이 든 곳 (기준 4: 1차는 방파제·항구·해변)
- 연륙 여부 추정 (기준 2): 육지 지명 / 연륙교로 이어진 섬 목록 / 그 밖의 섬(배 필요 → 제외)
- 해경 출입통제구역 200m 안은 이미 빠져 있음, 연안위험구역 「사망사고 발생구역」은 제외 (기준 5)
- 바다별 몫(동해 8 · 서해 8 · 남해 8 · 제주 6), 한 시군에서 최대 2곳

사람이 확인해야 하는 것 (표에 「확인 필요」로 남긴다)
- 기준 1 방문 지점(방파제 입구·주차장) — 위성지도·로드뷰
- 기준 2 연륙 「추정」이 맞는지
- 기준 3 시군 낚시통제구역 고시 · 관할 해경서 출입통제 공고 · 항만 출입 규정

실행 (backend 폴더): python -m scripts.explore_candidates  → docs/01_기획/탐험30선_후보.md
"""

import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(__file__).resolve().parent.parent / "seeds" / "rock_points.json"
OUT = ROOT / "docs" / "01_기획" / "탐험30선_후보.md"

ACCESS = re.compile(r"방파제|항|선창|포구|해수욕장|해변|등대|선착장|부두")
QUOTA = {"동해": 8, "서해": 8, "남해": 8, "제주": 6}
RESERVE = 4
PER_SIGUNGU = 2

# 연륙교·연륙도로로 차가 들어가는 섬 (2026-11 기준 지식 — 표에는 「추정」으로 적고 확인한다)
BRIDGED = {
    "신지도",
    "안면도",
    "원산도",
    "거제도",
    "거금도",
    "나로도",
    "암태도",
    "자은도",
    "임자도",
    "사옥도",
    "증도",
    "무의도",
    "석모도",
    "돌산도",
    "미륵도",
    "남해도",
    "창선도",
    "칠천도",
    "가조도",
    "진도",
    "선유도",
    "무녀도",
    "장자도",
    "신시도",
    "영흥도",
    "선재도",
    "대부도",
    "구봉도",
    "낭도",
}
JEJU_MAIN = ("제주도 북", "제주도 동", "제주도 남", "제주도 서")
MAINLAND_AREA = ("여수엑스포", "순천만", "광양만", "해남반도")


def sea(admin: str) -> str:
    if admin.startswith("제주"):
        return "제주"
    if admin.startswith(("강원", "경상북도", "울산")):
        return "동해"
    if admin.startswith(("부산", "경상남도")):
        return "남해"
    if admin.startswith(("인천", "경기", "충청", "전라북도")):
        return "서해"
    if admin.startswith("전라남도"):
        return "서해" if any(x in admin for x in ("신안", "영광", "무안", "목포", "함평")) else "남해"
    return "?"


def access(area: str, name: str) -> tuple[str, int]:
    """(설명, 우선순위: 0 육지 · 1 연륙 추정 · 9 배 필요). 지역명과 포인트 이름에 든 섬 이름을 함께 본다"""
    a = area.strip()
    named = [x for x in re.findall(r"([가-힣]+도)(?=[\s·]|해|등|항|$)", name) if len(x) >= 2]
    if any(x not in BRIDGED for x in named) or "우도" in name or "실미도" in name:
        return "배 필요 (제외)", 9  # 이름에 연륙 안 된 섬(삽시도·비양도·실미도 등)이 있으면 제외
    if a.startswith(JEJU_MAIN):
        return "제주 본섬", 0
    if a.startswith(MAINLAND_AREA) or not re.search(r"도(\s|·|$)|군도|열도|수도", a):
        return "육지", 0
    islands = [x.strip() for x in re.split(r"[·\s]", a) if x.strip().endswith("도")]
    if named and all(x in BRIDGED for x in named):
        return "연륙 추정 (확인 필요)", 1
    if any(x in BRIDGED for x in islands):
        return "연륙 추정 (확인 필요)", 1
    return "배 필요 (제외)", 9


SPOT = re.compile(r"([가-힣0-9][가-힣0-9 ]*?(?:항|포구|방파제|해수욕장|해변|선창|선착장))")
# 우도(배 필요) — 지역명이 「제주도 북동부·우도」로 본섬과 섞여 있어 좌표로 가른다
UDO = (33.48, 33.54, 126.92, 126.99)
# 지난 조사(2026-11-12)에서 지자체·관광공사의 긍정 근거가 있어 「조건부 가능」이었던 곳 → 먼저
PRIOR = {"봉포해변", "남애", "아야진"}  # spot_key 기준


def spot_of(name: str) -> str | None:
    """방문 지점 이름: 「어달리항 남측 갯바위」 → 「어달리항」. 항구·방파제·해변이 이름에 없으면 None (1차 대상 아님)"""
    m = SPOT.search(name.strip())
    return m[1].strip() if m else None


def spot_key(spot: str) -> str:
    """같은 곳 묶기: 「아야진 방파제」·「아야진항」 → 「아야진」"""
    return re.sub(r"(항|방파제)$", "", spot.replace(" ", ""))


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    pts = [p for p in data["points"] if ACCESS.search(p["name"])]
    rows, dropped = [], Counter()
    for p in pts:
        how, rank = access(p["area"], p["name"])
        if rank == 9:
            dropped["배 필요(섬)"] += 1
            continue
        if UDO[0] <= p["lat"] <= UDO[1] and UDO[2] <= p["lon"] <= UDO[3]:
            dropped["배 필요(섬)"] += 1
            continue
        if not spot_of(p["name"]):
            dropped["항구·방파제·해변 아님(갯바위만)"] += 1
            continue
        if p["danger"] and p["danger"].startswith("사망사고"):
            dropped["사망사고 발생구역"] += 1
            continue
        kind = (
            0 if re.search(r"방파제|항|선창|포구|선착장|부두", p["name"]) else 1
        )  # 방파제·항 먼저, 해변은 다음
        rows.append((sea(p["admin"]), rank, kind, bool(p["danger"]), p, how))

    # 같은 시군의 같은 항구·방파제·해변은 한 후보로 묶는다 (포인트 여러 개 → 대상어·위험구역 합침)
    spots: dict[tuple[str, str], dict] = {}
    for s, rank, kind, _danger, p, how in rows:
        spot = spot_of(p["name"])
        key = (p["admin"], spot_key(spot))
        g = spots.setdefault(
            key, {"sea": s, "rank": rank, "kind": kind, "how": how, "pts": [], "danger": set(), "name": spot}
        )
        if spot.endswith("항"):
            g["name"] = spot  # 이름은 「~항」을 우선
        g["pts"].append(p)
        g["rank"], g["kind"] = min(g["rank"], rank), min(g["kind"], kind)
        if p["danger"]:
            g["danger"].add(p["danger"])
    picked: dict[str, list] = defaultdict(list)
    per_sgg: Counter = Counter()
    order = sorted(
        spots.items(),
        key=lambda kv: (
            kv[0][1] not in PRIOR,
            kv[1]["rank"],
            kv[1]["kind"],
            bool(kv[1]["danger"]),
            -len(kv[1]["pts"]),
            kv[0],
        ),
    )
    for (admin, _key), g in order:
        spot = g["name"]
        s = g["sea"]
        if len(picked[s]) >= QUOTA.get(s, 0) + RESERVE or per_sgg[admin] >= PER_SIGUNGU:
            continue
        per_sgg[admin] += 1
        picked[s].append((spot, admin, g))

    lines = [
        "# 탐험 30선 후보 (2단계)",
        "",
        f"> 생성 {date.today().isoformat()} · `backend/scripts/explore_candidates.py` · 기준은 [확장_기능_설계.md](확장_기능_설계.md) 2장(2026-11-19 개정)",
        "> **모두 「후보 · 확인 필요」다.** 낚시 가능·접근 가능으로 판단한 목록이 아니다. 아래 ①~③을 사람이 확인해야 「검증 완료」가 된다.",
        "> **③ 제한 확인 결과(2026-11-19)는 [탐험30선_검증기록.md](탐험30선_검증기록.md)** — 이 파일은 스크립트로 다시 만들어지므로 확인 결과는 거기에 쌓는다.",
        "",
        "## 자동으로 거른 결과",
        "",
        f"- 시작: 해수부 갯바위낚시포인트 참고 포인트 {len(data['points'])}곳 (해경 출입통제구역 200m 안은 이미 제외)",
        f"- 이름이 방파제·항·포구·해변 등인 곳 {len(pts)}곳 → 제외: 섬이라 배가 필요 {dropped['배 필요(섬)']}곳 · "
        f"항구·해변 없는 갯바위 {dropped['항구·방파제·해변 아님(갯바위만)']}곳 · "
        f"사망사고 발생구역 {dropped['사망사고 발생구역']}곳 → 남은 {len(rows)}곳 → "
        f"**항구·방파제·해변 단위로 묶어 {len(spots)}곳**",
        "- 후보는 갯바위가 아니라 **그 항구·방파제·해변 자체**다 (1차 기준 4). 「근처 해수부 포인트」는 대상어 참고용",
        f"- 바다별 몫(동해 8 · 서해 8 · 남해 8 · 제주 6) + 예비 {RESERVE}곳씩, 한 시군 최대 {PER_SIGUNGU}곳",
        "- 순서: 지난 조사의 「조건부 가능」(봉포해변·남애항·아야진) → 육지 → 연륙 추정, 방파제·항 → 해변, 위험구역 아닌 곳 → 위험구역",
        "",
        "## 사람이 확인할 것 (곳마다)",
        "",
        "| 기준 | 확인 | 방법 |",
        "|---|---|---|",
        "| ① 방문 지점 | 방파제 입구·진입로·주차장 좌표 | 「지도」 링크 → 위성·로드뷰 |",
        "| ② 접근 | 「연륙 추정」이 맞는지, 차·도보로 갈 수 있는지 | 지도 |",
        "| ③ 제한 | 시군 낚시통제구역 고시 · 관할 해경서 출입통제 공고 · 항만 출입 규정 | 아래 「시군별 확인 목록」 |",
        "",
    ]
    for s in ("동해", "서해", "남해", "제주"):
        lines += [
            f"## {s} — 몫 {QUOTA[s]}곳 (+예비)",
            "",
            "| # | 방문 지점 (후보) | 시군 | 접근(②) | 근처 해수부 포인트 | 대상어 | 위험구역 | 지도 | ① | ③ |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        if len(picked[s]) < QUOTA[s]:
            lines.insert(
                len(lines) - 3,
                f"> 자동 기준을 통과한 곳이 {len(picked[s])}곳뿐이라 몫({QUOTA[s]}곳)을 못 채웠다. 기준을 낮추지 않는다.\n",
            )
        for i, (spot, admin, g) in enumerate(picked[s], 1):
            p0 = g["pts"][0]
            fish = sorted({c["species"] for p in g["pts"] for c in p["catches"]})
            mark = "" if i <= QUOTA[s] else " (예비)"
            link = f"[지도](https://map.kakao.com/link/map/{spot},{p0['lat']},{p0['lon']})"
            names = " / ".join(p["name"].strip() for p in g["pts"][:3])
            lines.append(
                f"| {i}{mark} | **{spot}** | {admin} | {g['how']} | {names} | {', '.join(fish[:4]) or '-'} | "
                f"{' / '.join(sorted(g['danger'])) or '-'} | {link} | 확인 필요 | 확인 필요 |"
            )
        lines.append("")

    sgg = sorted({admin for v in picked.values() for _, admin, _ in v})
    lines += [
        "## 시군별 확인 목록 (③)",
        "",
        "> 지난 조사(2026-11-12)에서 공공데이터로 바다 쪽 낚시통제구역 고시를 확인한 시군: 부산 수영·기장, 강릉, 속초, 경남 고성, 사천, 거제, 당진.",
        "> 나머지는 시군 고시 게시판을 직접 찾아야 한다. 게시판을 못 열면 「미확인」으로 두고 검증 완료로 올리지 않는다.",
        "",
        "| 시군 | 낚시통제구역 고시 | 해경 출입통제 공고 | 확인일 |",
        "|---|---|---|---|",
    ]
    lines += [f"| {x} | 확인 필요 | 확인 필요 | |" for x in sgg]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"남은 {len(rows)}곳 → 묶음 {len(spots)}곳 · 제외 {dict(dropped)} · 뽑음 { {k: len(v) for k, v in picked.items()} } · 시군 {len(sgg)}곳"
    )
    print(f"저장: {OUT}")


if __name__ == "__main__":
    main()
