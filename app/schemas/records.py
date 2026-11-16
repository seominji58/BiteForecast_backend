"""내 낚시 기록 요약 (서비스 개선 설계 R1): 어종별 최대어 · 첫 포획 · 잡은 어종 · 출조 일수.

기존 낚시일지를 집계만 한다 (새 표 없음). 개인 기록이므로 인증 여부와 관계없이 내 기록 전체를 쓰고,
인증 완료 여부는 표시로만 구분한다. 포인트(PERSONAL_BEST)는 지금처럼 인증 완료 기록만 계산한다.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class SpeciesRecordOut(BaseModel):
    key: str  # 비교 단위 (code:rockfish / etc:쥐노래미)
    species_code: str | None
    species_name: str
    first_at: datetime  # 처음 잡은 기록의 출조 일시
    first_journal_id: int
    journal_count: int  # 이 어종을 잡은 기록 수
    catch_count: int  # 마릿수 합 (마릿수를 비운 기록은 1마리로 셈하지 않고 0)
    best_length_cm: float | None
    best_journal_id: int | None
    best_at: datetime | None
    best_verified: bool  # 최대어 기록이 인증 완료인지


class RecordSummaryOut(BaseModel):
    journal_count: int  # 기록 수
    trip_days: int  # 출조 일수 (한국 날짜 기준, 같은 날 여러 기록은 하루)
    skunk_days: int  # 못 잡은 날 (그날 기록이 모두 마릿수 0)
    first_trip: date | None
    last_trip: date | None
    species: list[SpeciesRecordOut]  # 처음 잡은 순


class MilestoneOut(BaseModel):
    """방금 저장한 기록으로 생긴 일 — 저장 직후 한 번 보여준다"""

    kind: Literal["first_catch", "personal_best"]
    species_name: str
    length_cm: float | None
    previous_cm: float | None  # personal_best 일 때 이전 최대
