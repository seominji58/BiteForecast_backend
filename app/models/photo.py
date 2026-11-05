"""사진 (FR-09, 재설계 v2 §9).

업로드 → 서버가 EXIF(위치 포함)를 지운 사본만 저장 → 일지 또는 게시글에 연결.
- 업로드 직후에는 어디에도 연결되지 않은 상태(journal_id·post_id 모두 NULL). 저장 요청 때 연결한다
- purpose 로 인증용(일지)과 일반 게시글 사진을 구분한다. 게시글 사진은 포인트와 무관하다
- sha256·taken_at 은 관리자 검토용 참고 정보다 (자동 반려에 쓰지 않음)
"""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, str_enum
from app.models.enums import PhotoPurpose


class Photo(TimestampMixin, Base):
    __tablename__ = "photo"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[PhotoPurpose] = mapped_column(str_enum(PhotoPurpose))
    journal_id: Mapped[int | None] = mapped_column(ForeignKey("journal.id", ondelete="SET NULL"), index=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("post.id", ondelete="SET NULL"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    path: Mapped[str] = mapped_column(String(255))  # media 폴더 기준 상대 경로 (EXIF 제거본)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    # 원본 파일 해시: 같은 사진 재사용 확인용 (참고 정보)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    # 원본 EXIF 촬영 시각 (없으면 NULL = 확인 불가). 원본 EXIF 는 저장하지 않는다
    taken_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    taken_at_source: Mapped[str | None] = mapped_column(String(10))  # "exif" | "device"
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
