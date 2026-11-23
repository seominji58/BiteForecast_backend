"""금어기·금지체장 (수산자원관리법 시행령 별표1·별표2) → seeds/fishing_rules.json — 2026-11-23.

원문: 국가법령정보센터 PDF
  (06_개발환경/data_raw/수산자원관리법시행령_별표1_금지기간.pdf · _별표2_금지체장.pdf)
- 별표1 <개정 2026. 6. 23.>, 별표2 <개정 2024. 6. 4.>
- 사람이 원문을 보고 옮겼다. 원문이 바뀌면 이 파일을 고치고 다시 실행한다.
- 기간은 "MM-DD" 시작·끝(끝 포함). 해를 넘기면 끝이 시작보다 앞선다.
- region: 그 기간이 적용되는 곳(없으면 전국)
- notice: 해수부·시도 고시로 실제 기간이 정해짐 → 앱은 「고시 확인」으로만 안내
- 지난 한시 규정(2024년 가자미류 17cm)은 넣지 않았다.

실행: .venv/bin/python -m scripts.build_fishing_rules
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "seeds" / "fishing_rules.json"


def p(frm, to, region=None):
    return {"from": frm, "to": to, "region": region}


# (이름, 분류, 학명, 기간들, 고시 여부, 비고)
BAN = [
    ("대구", "어류", "Gadus macrocephalus", [p("01-16", "02-15")], False, None),
    ("문치가자미", "어류", "Pleuronectes yokohamae", [p("12-01", "01-31")], False, None),
    ("연어", "어류", "Oncorhynchus keta", [p("10-01", "11-30")], False, None),
    ("전어", "어류", "Konosirus punctatus", [p("05-01", "07-15")], False, "강원·경북은 제외"),
    (
        "쥐노래미",
        "어류",
        "Hexagrammos otakii",
        [p("11-01", "12-31")],
        False,
        "백령도·대청도 주변 지정 해역(주3)은 11.15~12.14",
    ),
    ("참홍어", "어류", "Raja pulchra", [p("06-01", "07-15")], False, None),
    (
        "참조기",
        "어류",
        "Larimichthys polyactis",
        [p("07-01", "07-31")],
        False,
        "근해 유자망은 4.22~8.10 · 어업 혼획 10% 미만 예외",
    ),
    (
        "갈치",
        "어류",
        "Trichiurus lepturus",
        [p("07-01", "07-31", "북위 33도 이북 해역")],
        False,
        "근해채낚기·연안복합어업 제외 · 어업 혼획 10% 미만 예외",
    ),
    (
        "고등어",
        "어류",
        "Scomber japonicus",
        [p("04-01", "06-30")],
        True,
        "4.1~6.30 중 1개월을 해양수산부장관이 고시",
    ),
    (
        "말쥐치",
        "어류",
        "Thamnaconus modestus",
        [p("05-01", "07-31")],
        False,
        "정치망·연안·구획어업은 6.1~7.31",
    ),
    ("옥돔", "어류", "Branchiostegus japonicus", [p("07-21", "08-20")], False, None),
    ("명태", "어류", "Theragra chalcogramma", [p("01-01", "12-31")], False, "연중 금지"),
    ("삼치", "어류", "Scomberomorus niphonius", [p("05-01", "05-31")], False, None),
    ("감성돔", "어류", "Acanthopagrus schlegelii", [p("05-01", "05-31")], False, None),
    (
        "꽃게",
        "갑각류",
        "Portunus trituberculatus",
        [p("06-01", "09-30")],
        True,
        "6.1~9.30 중 2개월 이내를 해양수산부장관이 고시",
    ),
    (
        "대게류",
        "갑각류",
        "Chionoecetes spp.",
        [p("06-01", "11-30")],
        False,
        "붉은대게 제외 · 동경 131°30′ 동쪽은 6.1~10.31 · 고성 일부 해역·울릉 인근 해역은 기간 다름(원문)",
    ),
    (
        "붉은대게",
        "갑각류",
        "Chionoecetes japonicus",
        [p("07-10", "08-25")],
        False,
        "강원 연안자망은 6.1~7.10",
    ),
    ("대하", "갑각류", "Penaeus orientalis", [p("05-01", "06-30")], False, None),
    (
        "새조개",
        "패류",
        "Fulvia mutica",
        [
            p("06-16", "09-30", "아래 지역 외"),
            p("06-01", "09-30", "부산·울산·경남·전남(무안·영광 제외)·제주"),
        ],
        False,
        None,
    ),
    (
        "소라",
        "패류",
        "Batillus cornutus",
        [
            p("06-01", "06-30", "여수 삼산면"),
            p("06-01", "08-31", "제주(추자도 제외)"),
            p("07-01", "08-31", "제주 추자도"),
            p("06-01", "07-31", "울릉도·독도"),
        ],
        False,
        "표시한 지역에만 금어기",
    ),
    (
        "전복류",
        "패류",
        "Haliotis spp.",
        [p("09-01", "10-31", "제주 외"), p("10-01", "12-31", "제주")],
        False,
        None,
    ),
    ("코끼리조개", "패류", "Panopea japonica", [p("05-01", "06-30", "강원·경북")], False, None),
    ("키조개", "패류", "Atrina pectinata", [p("07-01", "08-31")], False, None),
    (
        "가리비",
        "패류",
        "Patinopecten yessoensis",
        [p("03-01", "06-30", "포항 앞 지정 해역(주7)")],
        False,
        None,
    ),
    ("오분자기", "패류", "Sulculus diversicolor", [p("07-01", "08-31", "제주")], False, None),
    (
        "넓미역",
        "해조류",
        "Undariopsis peterseniana",
        [p("09-01", "11-30", "제주")],
        True,
        "제주도지사가 5.1~11.30 중 3개월 이상 따로 고시 가능",
    ),
    ("우뭇가사리", "해조류", "Gelidium amansii", [p("11-01", "03-31")], False, None),
    ("톳", "해조류", "Hizikia fusiformis", [p("10-01", "01-31")], False, None),
    ("해삼", "기타", "Stichopus japonicus", [p("07-01", "07-31")], False, None),
    (
        "살오징어",
        "기타",
        "Todarodes pacificus",
        [p("04-01", "05-31")],
        False,
        "근해채낚기·연안복합·정치망어업은 4.1~4.30",
    ),
    (
        "낙지",
        "기타",
        "Octopus minor",
        [p("06-01", "06-30")],
        True,
        "시·도지사가 4.1~9.30 중 1개월 이상을 지역별로 고시하면 그 기간",
    ),
    ("주꾸미", "기타", "Amphioctopus fangsiao", [p("05-11", "08-31")], False, None),
    (
        "참문어",
        "기타",
        "Octopus vulgaris",
        [p("05-16", "06-30")],
        True,
        "시·도지사가 5.1~9.15 중 46일 이상을 지역별로 고시하면 그 기간",
    ),
]

# (이름, 분류, 기준 글, 계측, 비고)
SIZE = [
    ("문치가자미", "어류", "20cm 이하", "전장", None),
    ("참가자미", "어류", "20cm 이하", "전장", None),
    ("감성돔", "어류", "25cm 이하", "전장", None),
    ("돌돔", "어류", "24cm 이하", "전장", None),
    ("참돔", "어류", "24cm 이하", "전장", None),
    ("넙치", "어류", "35cm 이하", "전장", None),
    ("농어", "어류", "30cm 이하", "전장", None),
    ("대구", "어류", "35cm 이하", "전장", None),
    ("도루묵", "어류", "11cm 이하", "전장", None),
    ("민어", "어류", "33cm 이하", "전장", None),
    ("방어", "어류", "30cm 이하", "전장", None),
    ("볼락", "어류", "15cm 이하", "전장", None),
    ("붕장어", "어류", "35cm 이하", "전장", None),
    ("조피볼락", "어류", "23cm 이하", "전장", None),
    ("쥐노래미", "어류", "20cm 이하", "전장", None),
    ("참홍어", "어류", "42cm 이하", "체반폭", None),
    ("갈치", "어류", "18cm 이하", "항문장", "어업 혼획 20% 미만 예외"),
    ("고등어", "어류", "21cm 이하", "전장", "어업 혼획 20% 미만 예외"),
    ("참조기", "어류", "15cm 이하", "전장", "어업 혼획 20% 미만 예외"),
    ("말쥐치", "어류", "18cm 이하", "전장", None),
    ("갯장어", "어류", "40cm 이하", "전장", None),
    ("미거지", "어류", "40cm 이하", "전장", None),
    ("용가자미", "어류", "20cm 이하", "전장", None),
    ("기름가자미", "어류", "20cm 이하", "전장", None),
    ("청어", "어류", "20cm 이하", "전장", None),
    ("꽃게", "갑각류", "6.4cm 이하", "두흉갑장", None),
    ("대게", "갑각류", "9cm 이하", "두흉갑장", None),
    ("소라", "패류", "5cm 이하", "각고", "제주·울릉도·독도산은 7cm 이하"),
    ("오분자기", "패류", "4cm 이하", "각장", "제주산에 한정"),
    ("전복류", "패류", "7cm 이하", "각장", "제주산은 10cm 이하"),
    ("기수재첩", "패류", "1.5cm 이하", "각장", None),
    ("키조개", "패류", "18cm 이하", "각장", "부산·울산·강원·경북·경남산에 한정"),
    ("대문어", "기타", "600g 이하", "체중", None),
    ("살오징어", "기타", "15cm 이하", "외투장", "어업 혼획 20% 미만 예외"),
]

# 앱 어종 코드 → 법령 이름 (frontend/src/lib/species.ts 코드와 같다)
APP_SPECIES = {
    "rockfish": ["조피볼락"],
    "black_porgy": ["감성돔"],
    "seabass": ["농어"],
    "rock_bream": ["돌돔"],
    "red_seabream": ["참돔"],
    "black_rockfish": ["볼락"],
    "flatfish": ["넙치"],
    "webfoot_octopus": ["주꾸미"],
    "octopus": ["참문어", "대문어"],
    "hairtail": ["갈치"],
    "mackerel": ["고등어"],
    "conger": ["붕장어"],
    "greenling": ["쥐노래미"],
    "marbled_flounder": ["문치가자미"],
}

MEASURE = {
    "전장": "주둥이에서 꼬리지느러미 끝까지",
    "항문장": "주둥이에서 항문까지",
    "체반폭": "양쪽 가슴지느러미 사이 너비",
    "두흉갑장": "머리·가슴 껍데기 길이",
    "각장": "껍데기 길이",
    "각고": "껍데기 높이",
    "외투장": "외투막 길이",
    "체중": "무게",
}


def main() -> None:
    data = {
        "_note": "scripts/build_fishing_rules.py 로 생성 — 직접 고치지 말 것",
        "source": "수산자원관리법 시행령 별표1(개정 2026.6.23.)·별표2(개정 2024.6.4.), 국가법령정보센터",
        "law_url": "https://www.law.go.kr/법령/수산자원관리법시행령",
        "checked_at": "2026-11-23",
        "notice": "법령 요약이에요. 어업 방법·해역별 예외와 해양수산부·시도 고시는 원문을 확인하세요. "
        "금어기에 잡았거나 금지체장 이하는 바로 놓아주세요. 비어업인도 1천만원 이하 벌금 대상이에요.",
        "ban": [
            {"name": n, "group": g, "sci": s, "periods": ps, "notice": nt, "note": note}
            for n, g, s, ps, nt, note in BAN
        ],
        "size": [
            {"name": n, "group": g, "limit": lim, "measure": m, "measure_desc": MEASURE[m], "note": note}
            for n, g, lim, m, note in SIZE
        ],
        "app_species": APP_SPECIES,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"금어기 {len(BAN)} · 금지체장 {len(SIZE)} → {OUT.name}")


if __name__ == "__main__":
    main()
