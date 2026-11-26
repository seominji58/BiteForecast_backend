"""입력 검사 오류를 앱에 그대로 보여 줄 한국어 문장으로 (2026-11-26).

친구 테스트: 이모티콘 하나짜리 제목을 올리자 「String should have at least 2 characters」(영어 원문)가 떴다.
pydantic 오류 type·ctx 와 칸 이름으로 「제목은 1자 이상 입력해 주세요」처럼 바꾼다. 모르는 칸은 「입력값」.
"""

FIELD = {
    "title": "제목",
    "body": "내용",
    "content": "내용",
    "name": "이름",
    "nickname": "닉네임",
    "memo": "메모",
    "bait": "미끼",
    "rig": "채비",
    "count": "마릿수",
    "max_length_cm": "최대 길이",
    "species_etc": "어종 이름",
    "species_code": "어종",
    "label": "준비물 이름",
    "reason": "신고 사유",
    "email": "이메일",
    "password": "비밀번호",
    "region": "지역",
    "lat": "위도",
    "lon": "경도",
    "photo_ids": "사진",
    "stops": "장소",
    "checklist": "준비물",
    "messages": "질문",
    "fished_at": "출조 일시",
    "start_date": "시작 날짜",
    "end_date": "끝 날짜",
    "place_id": "낚시터",
    "category": "분류",
    "file": "사진 파일",
}

UNIT = {"max_length_cm": "cm", "count": "마리"}


def _josa(word: str, a: str, b: str) -> str:
    """받침이 있으면 a, 없으면 b (은/는, 을/를)"""
    ch = word[-1]
    if "가" <= ch <= "힣":
        return a if (ord(ch) - 0xAC00) % 28 else b
    return a


def _field(loc: list) -> tuple[str, str]:
    key = next(
        (str(x) for x in reversed(loc) if isinstance(x, str) and x not in ("body", "query", "path")), ""
    )
    if not key and loc and loc[-1] == "body":
        key = ""
    return key, FIELD.get(key, "입력값")


def ko_message(err: dict) -> str:
    t = err.get("type", "")
    ctx = err.get("ctx") or {}
    key, name = _field(list(err.get("loc", ())))
    eun = name + _josa(name, "은", "는")
    unit = UNIT.get(key, "")
    msg = str(err.get("msg", ""))
    if t == "value_error":  # 우리가 직접 쓴 한국어 문장
        return msg.removeprefix("Value error, ")
    if t == "missing":
        return f"{name}{_josa(name, '을', '를')} 입력해 주세요"
    if t == "string_too_short":
        n = ctx.get("min_length", 1)
        return (
            f"{name}{_josa(name, '을', '를')} 입력해 주세요" if n <= 1 else f"{eun} {n}자 이상 입력해 주세요"
        )
    if t == "string_too_long":
        return f"{eun} {ctx.get('max_length')}자까지 쓸 수 있어요"
    if t == "too_short":
        return f"{eun} {ctx.get('min_length')}개 이상 골라 주세요"
    if t == "too_long":
        return f"{eun} {ctx.get('max_length')}개까지 고를 수 있어요"
    if t in ("less_than_equal", "less_than"):
        return f"{eun} {ctx.get('le', ctx.get('lt'))}{unit} 이하로 입력해 주세요"
    if t in ("greater_than", "greater_than_equal"):
        g = ctx.get("gt", ctx.get("ge"))
        return f"{eun} {g}{unit}보다 커야 해요" if t == "greater_than" else f"{eun} {g}{unit} 이상이어야 해요"
    if t in ("int_parsing", "float_parsing", "int_type", "float_type", "int_from_float"):
        return f"{eun} 숫자로 입력해 주세요"
    if t in ("datetime_parsing", "datetime_from_date_parsing", "date_parsing", "date_from_datetime_parsing"):
        return f"{name} 형식이 올바르지 않아요"
    if t in ("enum", "literal_error"):
        return f"{name} 값이 올바르지 않아요"
    if t == "string_type":
        return f"{eun} 글자로 입력해 주세요"
    if t == "json_invalid":
        return "요청 형식이 올바르지 않아요. 앱을 다시 실행해 주세요"
    if t == "string_pattern_mismatch":
        return f"{name} 형식이 올바르지 않아요"
    # 그 밖: 한글이 이미 들어 있으면 그대로, 아니면 일반 문장 (영어 원문을 그대로 보이지 않게)
    if any("가" <= c <= "힣" for c in msg):
        return msg.removeprefix("Value error, ")
    return f"{name} 값이 올바르지 않아요"
