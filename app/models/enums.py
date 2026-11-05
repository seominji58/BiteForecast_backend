from enum import StrEnum


class PlaceType(StrEnum):
    BREAKWATER = "breakwater"  # 방파제
    ROCK = "rock"  # 갯바위
    WHARF = "wharf"  # 선착장
    BEACH = "beach"  # 해변
    OTHER = "other"


class StationKind(StrEnum):
    TIDE = "tide"  # 조위관측소
    BUOY = "buoy"  # 해양관측부이
    KMA = "kma"  # 기상청 지점/격자


class StationRole(StrEnum):
    TIDE = "tide"
    OCEAN = "ocean"


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
