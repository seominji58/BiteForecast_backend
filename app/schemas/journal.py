from datetime import UTC, datetime, timedelta

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from app.models.enums import DataKind, Metric, PointReason, VerificationStatus
from app.schemas.common import ORMModel
from app.schemas.me import MyTitleOut
from app.schemas.photo import PhotoOut

# 기기 시계 오차 허용
_FUTURE_TOLERANCE = timedelta(minutes=5)


class JournalIn(BaseModel):
    """낚시일지 입력 (FR-08). 출조 일시는 timezone 포함 ISO 8601 (예: 2026-11-08T06:00:00+09:00)"""

    place_id: int
    fished_at: AwareDatetime
    species_code: str | None = Field(default=None, max_length=30)
    species_etc: str | None = Field(default=None, max_length=50)
    count: int | None = Field(default=None, ge=0, le=999)
    max_length_cm: float | None = Field(default=None, gt=0, le=300)
    bait: str | None = Field(default=None, max_length=50)
    rig: str | None = Field(default=None, max_length=50)
    memo: str | None = Field(default=None, max_length=1000)
    # 업로드해 둔 사진 ID (순서 = 표시 순서). None 이면 사진 변경 없음, [] 이면 모두 뺌
    photo_ids: list[int] | None = Field(default=None, max_length=10)
    # 「저장하고 인증 신청」: 저장과 함께 인증 검토를 신청 (사진 1장 이상·어종 필요)
    request_verification: bool = False

    @field_validator("species_code", "species_etc", "bait", "rig", "memo", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("fished_at")
    @classmethod
    def _not_future(cls, v: datetime) -> datetime:
        if v > datetime.now(UTC) + _FUTURE_TOLERANCE:
            raise ValueError("출조 일시는 미래일 수 없습니다")
        return v

    @field_validator("max_length_cm")
    @classmethod
    def _round_length(cls, v: float | None) -> float | None:
        return None if v is None else round(v, 1)

    @model_validator(mode="after")
    def _one_species_field(self):
        if self.species_code and self.species_etc:
            raise ValueError("어종은 목록 선택(species_code)과 직접 입력(species_etc) 중 하나만 입력합니다")
        return self


class EnvSnapshotOut(ORMModel):
    metric: Metric
    kind: DataKind | None  # None = 연결된 자료 없음
    value: float | None
    unit: str
    value_time: datetime | None
    distance_km: float | None
    source_agency: str | None


class VerificationOut(BaseModel):
    """사진 인증 상태. points = 이 일지로 현재 받은 포인트 합계 (인증 완료일 때만 0 초과)"""

    status: VerificationStatus
    requested_at: datetime | None
    reviewed_at: datetime | None
    reject_reason: str | None
    points: int
    # 지금 인증 신청이 가능한지와, 불가하면 빠진 조건 (예: 「사진 1장 이상」)
    can_request: bool
    missing: list[str]


class JournalOut(BaseModel):
    id: int
    place_id: int
    place_name: str
    fished_at: datetime
    species_code: str | None
    species_name: str | None  # 목록 어종명 또는 직접 입력값
    species_etc: str | None
    count: int | None
    max_length_cm: float | None
    bait: str | None
    rig: str | None
    memo: str | None
    photo_count: int
    photos: list[PhotoOut]
    verification: VerificationOut
    # 이 일지를 공유한 커뮤니티 글 (없으면 None)
    shared_post_id: int | None
    created_at: datetime
    updated_at: datetime
    env_snapshots: list[EnvSnapshotOut]


class JournalMutationOut(BaseModel):
    """일지 생성/수정/삭제 결과. 앱은 point_delta 로 토스트, title_changed 로 칭호 변경 안내"""

    journal: JournalOut | None  # 삭제 시 None
    point_delta: int
    total_points: int
    title: MyTitleOut
    title_changed: bool


class SpeciesOut(ORMModel):
    code: str
    name_ko: str


class PointHistoryItem(ORMModel):
    id: int
    reason: PointReason
    delta: int
    journal_id: int | None
    created_at: datetime


class MyPointsOut(BaseModel):
    total_points: int
    history: list[PointHistoryItem]
