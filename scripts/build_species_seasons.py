"""앱 어종별 산란기(난태생은 새끼 낳는 시기) → seeds/species_seasons.json (2026-11-23).

근거 (원문에서 직접 읽은 값만, 06_개발환경/data_raw 에 원본 보관)
- 국립수산과학원 「주요생물 생태와 생활사」 (국립수산과학원_주요생물생태와생활사_46종_20261123.json)
- 국내 학술지 논문 (어종_산란기_논문근거_20261123.json, KoreaScience)
원칙
- 「봄철」「가을~겨울」처럼 월이 없는 표현은 달력에 칠하지 않고 글로만 둔다 (text)
- 해역마다 다르면 해역별로 따로 둔다
- 실험실 수온(양식 실험 설정값)은 넣지 않는다. 자연 해역 값만 temps 에
- 국내 근거가 없는 어종(돌돔·벵에돔·열기·점성어·문치가자미 등)은 넣지 않는다 → 앱은 「자료 없음」
- 산란기는 「잘 잡히는 시기」가 아니다. 앱은 「산란기」로만 표시한다

실행: .venv/bin/python -m scripts.build_species_seasons
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "seeds" / "species_seasons.json"
NIFS = "국립수산과학원 「주요생물 생태와 생활사」"
NIFS_URL = "https://www.nifs.go.kr/contents/actionContentsCons0088.do"


def per(months, area=None, peak=None, cite=NIFS, url=NIFS_URL, note=None):
    return {"months": months, "peak": peak or [], "area": area, "cite": cite, "url": url, "note": note}


def rng(a, b):
    """월 범위 (해를 넘기면 이어 붙임). rng(11, 1) → [11, 12, 1]"""
    return list(range(a, b + 1)) if a <= b else list(range(a, 13)) + list(range(1, b + 1))


SEASONS = {
    "black_porgy": {
        "name": "감성돔",
        "periods": [
            per(
                rng(3, 7),
                "남해 여수",
                [5, 6],
                "Kwon 외 2009, 한국어류학회지 21(2)",
                "https://koreascience.or.kr/article/JAKO200910102404958.pub?lang=en",
            ),
            per(
                rng(4, 5),
                "남해 통영",
                None,
                "이해원 외 2021, 한국어류학회지 33(1)",
                "https://koreascience.or.kr/article/JAKO202123258346415.pub?lang=ko",
            ),
        ],
    },
    "rockfish": {
        "name": "우럭(조피볼락)",
        "kind": "birth",
        "periods": [
            per(
                rng(4, 5),
                None,
                None,
                "Baek 외 2000, 한국수산과학회지 33(5)",
                "https://koreascience.kr/article/JAKO200024839399930.page?lang=ko",
                "교미 11~12월",
            ),
        ],
    },
    "black_rockfish": {
        "name": "볼락",
        "kind": "birth",
        "periods": [
            per(
                rng(1, 2),
                "경남 통영",
                None,
                "이택열·김성연 1992, 한국수산과학회지 25(5)",
                "https://koreascience.kr/article/JAKO199223607640482.page?lang=ko",
                "교미 12월",
            ),
            per(
                [2],
                "남해 여수",
                None,
                "김희용 외 2010, 한국수산기술학회지 46(4)",
                "https://koreascience.kr/article/JAKO201008863883144.pdf",
            ),
        ],
    },
    "greenling": {
        "name": "노래미(쥐노래미)",
        "periods": [
            per(
                rng(9, 12),
                "서해",
                [11],
                "Kang 외 2004, 한국양식학회지 17(1)",
                "https://koreascience.kr/article/JAKO200411922205314.page?lang=ko",
            ),
            per(
                rng(10, 1),
                "인천 연안",
                [11, 12],
                "Lee 외 2023, 한국어류학회지 35(4)",
                "https://koreascience.or.kr/article/JAKO202319156693042.page?lang=ko",
            ),
        ],
    },
    "mullet": {
        "name": "숭어",
        "periods": [
            per(
                rng(11, 1),
                "제주",
                [12],
                "Kim 외 2004, 환경독성학회지 19(1)",
                "https://koreascience.kr/article/JAKO200412910502037.page?lang=ko",
            ),
            per(
                rng(11, 1),
                "여수",
                None,
                "Zhang 외 2011, 수산해양기술연구 47(3)",
                "https://koreascience.kr/article/JAKO201126235932904.page?lang=ko",
            ),
        ],
    },
    "webfoot_octopus": {
        "name": "주꾸미",
        "periods": [
            per(
                rng(4, 6),
                "서해 부안",
                [5, 6],
                "Son 외 2015, 한국패류학회지 31(2)",
                "https://koreascience.kr/article/JAKO201523047606750.page",
            ),
            per(
                rng(12, 5),
                "남해 전남",
                [3, 4, 5],
                "Moon 외 2022, 한국수산과학회지 55(1)",
                "https://koreascience.kr/article/JAKO202210351366840.page",
            ),
        ],
    },
    "octopus": {
        "name": "문어",
        "periods": [
            per(
                [5, 6, 9],
                "참문어 · 남해 통영·사천",
                [9],
                "Kang 외 2009, 한국패류학회지 25(2)",
                "https://koreascience.or.kr/article/JAKO200934152713250.page?lang=ko",
            ),
            per(
                rng(2, 5),
                "대문어 · 동해 강원",
                [3, 4, 5],
                "Lee 외 2014, 수산해양기술연구 50(2)",
                "https://koreascience.kr/article/JAKO201417048539546.page",
            ),
        ],
        "temps": [
            {
                "text": "대문어 어장: 바닥 수온 10℃ 미만에서 형성, 18℃ 넘으면 깊은 곳으로 이동 (동해 중부)",
                "cite": "Seo 외 2022, 수산해양기술연구 58(4)",
                "url": "https://koreascience.kr/article/JAKO202208757735339.page",
            },
        ],
    },
    "bigfin_squid": {
        "name": "무늬오징어",
        "periods": [
            per(
                rng(7, 9),
                "제주 (6~11월 조사)",
                [7],
                "Kang 외 2009, 한국패류학회지 25(2)",
                "https://koreascience.or.kr/article/JAKO200934152713260.page?lang=ko",
            ),
        ],
    },
    "goby": {
        "name": "망둥어(문절망둑)",
        "periods": [
            per(
                rng(2, 5),
                None,
                None,
                "Park 외 2005, 한국수산과학회지 38(5)",
                "https://koreascience.kr/article/JAKO200507523288759.page",
            ),
        ],
    },
    "red_seabream": {"name": "참돔", "periods": [per(rng(4, 7))]},
    "flatfish": {"name": "광어(넙치)", "periods": [per(rng(2, 6))]},
    "hairtail": {
        "name": "갈치",
        "periods": [per(rng(4, 8), "서·남해 연안")],
        "temps": [{"text": "산란 수온 18~20℃", "cite": NIFS, "url": NIFS_URL}],
    },
    "cuttlefish": {
        "name": "갑오징어",
        "periods": [per(rng(4, 6))],
        "temps": [{"text": "산란 수온 13~19℃ · 서식 수온 10~26℃", "cite": NIFS, "url": NIFS_URL}],
    },
    "horse_mackerel": {"name": "전갱이", "periods": [per(rng(6, 8), "제주도 근해")]},
    "seabass": {
        "name": "농어",
        "periods": [],
        "text": "산란기 봄철 (월은 원문에 없음)",
        "cite": NIFS,
        "url": NIFS_URL,
    },
    "mackerel": {
        "name": "고등어",
        "periods": [],
        "temps": [{"text": "산란 수온 15~20℃ (지역마다 다름)", "cite": NIFS, "url": NIFS_URL}],
    },
    "conger": {
        "name": "붕장어",
        "periods": [],
        "text": "산란기 4~5월 · 산란장은 일본 남부 먼바다 (우리 연안에서 산란하지 않음)",
        "cite": NIFS,
        "url": NIFS_URL,
    },
}


def main() -> None:
    data = {
        "_note": "scripts/build_species_seasons.py 로 생성 — 직접 고치지 말 것",
        "notice": "산란기는 잘 잡히는 시기와 같지 않아요. 연구된 해역 기준이라 다른 바다는 다를 수 있어요.",
        "species": {
            code: {"kind": "spawn", "temps": [], "text": None, "cite": None, "url": None, **v}
            for code, v in SEASONS.items()
        },
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(SEASONS)}종 → {OUT.name}")


if __name__ == "__main__":
    main()
