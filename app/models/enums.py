from enum import StrEnum


class PlaceType(StrEnum):
    BREAKWATER = "breakwater"  # 방파제
    ROCK = "rock"  # 갯바위
    WHARF = "wharf"  # 선착장
    BEACH = "beach"  # 해변
    PAID = "paid"  # 신고 유료 낚시터 (좌대·방갈로 등)
    POINT = "point"  # 낚시 포인트 (바다낚시지수 지점)
    BOAT = "boat"  # 선상 포인트 (해상)
    OTHER = "other"


class StationKind(StrEnum):
    TIDE = "tide"  # 조위관측소
    BUOY = "buoy"  # 해양관측부이
    KMA = "kma"  # 기상청 지점/격자
    FISHING_INDEX = "fishing_index"  # 바다낚시지수 지점


class StationRole(StrEnum):
    TIDE = "tide"  # 조석 예보지점
    OCEAN = "ocean"  # 해양관측 부이 (실측)
    FORECAST = "forecast"  # 기상청 단기예보 격자 (파고·풍속 예보)
    FISHING_INDEX = "fishing_index"  # 국립해양조사원 바다낚시지수 지점


class DataKind(StrEnum):
    """예보/실측 구분 (FR-07, TC-03)"""

    FORECAST = "forecast"
    OBSERVED = "observed"


class Metric(StrEnum):
    TIDE_LEVEL = "tide_level"
    WAVE_HEIGHT = "wave_height"
    WIND_SPEED = "wind_speed"
    WATER_TEMP = "water_temp"


class TideExtremeType(StrEnum):
    HIGH = "high"
    LOW = "low"


class PointReason(StrEnum):
    """포인트 적립 사유 (FR-11)"""

    JOURNAL_CREATED = "JOURNAL_CREATED"  # +10
    DETAIL_FILLED = "DETAIL_FILLED"  # +5
    PHOTO_ATTACHED = "PHOTO_ATTACHED"  # +5
    FIRST_PLACE = "FIRST_PLACE"  # +15
    PERSONAL_BEST = "PERSONAL_BEST"  # +20


class RestrictionType(StrEnum):
    FISHING = "fishing"
    ACCESS = "access"
    OTHER = "other"


class RegulationStatus(StrEnum):
    """규제 4단계 상태 (FR-17). 기본값은 UNVERIFIED"""

    PROHIBITED = "PROHIBITED"
    CONDITIONAL = "CONDITIONAL"
    OFFICIALLY_OPEN = "OFFICIALLY_OPEN"
    UNVERIFIED = "UNVERIFIED"


class ReportStatus(StrEnum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class VerificationStatus(StrEnum):
    """낚시일지 사진 인증 상태 (재설계 v2 §9). 포인트는 APPROVED 일지에서만 계산한다"""

    NONE = "none"  # 개인 기록 (신청 안 함)
    PENDING = "pending"  # 검토 대기
    APPROVED = "approved"  # 관리자 승인
    REJECTED = "rejected"  # 관리자 반려 (사유 포함)


class PhotoPurpose(StrEnum):
    """사진 용도. 인증용(일지)과 일반 게시글 사진을 구분한다 — 게시글 사진은 포인트와 무관"""

    JOURNAL = "journal"
    POST = "post"
