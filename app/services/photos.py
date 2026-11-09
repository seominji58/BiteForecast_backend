"""사진 업로드·연결·제공 (재설계 v2 §9).

개인정보 보호
- 원본은 저장하지 않는다. 방향만 반영해 다시 인코딩한 JPEG(EXIF·GPS 없음)만 남긴다
- 촬영 시각(EXIF DateTimeOriginal)과 원본 해시만 따로 보관한다 — 관리자 검토 참고용, 자동 반려에 쓰지 않음
- 사진 파일은 권한 확인 후에만 내려준다 (본인 / 공개 글에 붙은 사진 / 관리자)
"""

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AppUser, Journal, Photo, Post
from app.models.base import utcnow
from app.models.enums import PhotoPurpose, VerificationStatus
from app.schemas.photo import PhotoOut

KST = ZoneInfo("Asia/Seoul")
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}  # MPO = 일부 기기의 JPEG 변형
_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 36867
_OFFSET_TIME_ORIGINAL = 36881
_DATETIME = 306


def media_root() -> Path:
    root = Path(get_settings().media_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def photo_out(p: Photo) -> PhotoOut:
    return PhotoOut(id=p.id, url=f"/photos/{p.id}", width=p.width, height=p.height)


def _exif_taken_at(img: Image.Image) -> datetime | None:
    """EXIF 촬영 시각. 시간대 정보가 없으면 한국 시간으로 본다. 읽을 수 없으면 None (= 확인 불가)"""
    try:
        exif = img.getexif()
        ifd = exif.get_ifd(_EXIF_IFD)
        raw = ifd.get(_DATETIME_ORIGINAL) or exif.get(_DATETIME)
        if not raw:
            return None
        dt = datetime.strptime(str(raw).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
        offset = str(ifd.get(_OFFSET_TIME_ORIGINAL) or "").strip("\x00 ")
        if len(offset) == 6 and offset[0] in "+-":
            sign = 1 if offset[0] == "+" else -1
            hh, mm = offset[1:].split(":")
            tz = timezone(sign * timedelta(hours=int(hh), minutes=int(mm)))
            return dt.replace(tzinfo=tz).astimezone(UTC)
        return dt.replace(tzinfo=KST).astimezone(UTC)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        return None


def save_upload(
    db: Session, user: AppUser, purpose: PhotoPurpose, raw: bytes, device_taken_at: datetime | None
) -> Photo:
    s = get_settings()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="빈 파일입니다")
    if len(raw) > s.photo_max_bytes:
        raise HTTPException(
            status_code=400, detail=f"사진은 {s.photo_max_bytes // (1024 * 1024)}MB 이하만 올릴 수 있습니다"
        )
    try:
        img = Image.open(io.BytesIO(raw))
        fmt = img.format
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(status_code=400, detail="사진 파일을 읽을 수 없습니다 (JPEG·PNG·WEBP)") from None
    if fmt not in ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail="지원하지 않는 사진 형식입니다 (JPEG·PNG·WEBP)")

    taken_at = _exif_taken_at(img)
    taken_src = "exif" if taken_at else None
    if taken_at is None and device_taken_at is not None:
        taken_at, taken_src = device_taken_at.astimezone(UTC), "device"

    # 방향 반영 → RGB → 축소 → EXIF 없이 다시 저장 (위치 정보 제거)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
        img = bg
    img.thumbnail((s.photo_max_side, s.photo_max_side))
    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=85, optimize=True)
    data = out.getvalue()

    now = utcnow()
    rel = Path(f"{now:%Y}/{now:%m}/{uuid.uuid4().hex}.jpg")
    dest = media_root() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    photo = Photo(
        user_id=user.id,
        purpose=purpose,
        path=rel.as_posix(),
        width=img.width,
        height=img.height,
        size_bytes=len(data),
        sha256=hashlib.sha256(raw).hexdigest(),
        taken_at=taken_at,
        taken_at_source=taken_src,
    )
    db.add(photo)
    _purge_orphans(db, user)
    db.commit()
    return photo


def _purge_orphans(db: Session, user: AppUser) -> None:
    """올리고 저장하지 않은(어디에도 연결 안 된) 오래된 사진 정리"""
    cutoff = utcnow() - timedelta(hours=get_settings().photo_orphan_hours)
    for p in db.scalars(
        select(Photo).where(
            Photo.user_id == user.id,
            Photo.journal_id.is_(None),
            Photo.post_id.is_(None),
            Photo.deleted_at.is_(None),
            Photo.created_at < cutoff,
        )
    ):
        _soft_delete(p)


def _soft_delete(p: Photo) -> None:
    p.deleted_at = utcnow()
    (media_root() / p.path).unlink(missing_ok=True)


def attach(
    db: Session,
    user: AppUser,
    photo_ids: list[int] | None,
    purpose: PhotoPurpose,
    *,
    journal: Journal | None = None,
    post: Post | None = None,
) -> bool:
    """사진 목록을 일지 또는 글에 연결한다. photo_ids=None 이면 변경 없음. 반환: 사진 구성이 바뀌었는지"""
    if photo_ids is None:
        return False
    s = get_settings()
    ids = list(dict.fromkeys(photo_ids))
    if len(ids) > s.photo_max_per_item:
        raise HTTPException(status_code=400, detail=f"사진은 {s.photo_max_per_item}장까지 첨부할 수 있습니다")

    owner_col = Photo.journal_id if journal is not None else Photo.post_id
    owner_id = journal.id if journal is not None else post.id  # type: ignore[union-attr]
    current = list(db.scalars(select(Photo).where(owner_col == owner_id, Photo.deleted_at.is_(None))).all())

    wanted: list[Photo] = []
    for pid in ids:
        p = db.get(Photo, pid)
        ok = (
            p is not None
            and p.user_id == user.id
            and p.deleted_at is None
            and p.purpose == purpose
            and (
                (p.journal_id is None and p.post_id is None)
                or (journal is not None and p.journal_id == journal.id)
                or (post is not None and p.post_id == post.id)
            )
        )
        if not ok:
            raise HTTPException(status_code=400, detail="첨부할 수 없는 사진이 있습니다. 다시 올려 주세요")
        wanted.append(p)

    changed = [p.id for p in current] != [p.id for p in wanted]
    keep = {p.id for p in wanted}
    for p in current:
        if p.id not in keep:
            _soft_delete(p)
    for i, p in enumerate(wanted):
        if journal is not None:
            p.journal_id = journal.id
        else:
            p.post_id = post.id  # type: ignore[union-attr]
        p.sort_order = i
    db.flush()
    return changed


def delete_for(db: Session, *, journal: Journal | None = None, post: Post | None = None) -> None:
    col, oid = (Photo.journal_id, journal.id) if journal is not None else (Photo.post_id, post.id)  # type: ignore[union-attr]
    for p in db.scalars(select(Photo).where(col == oid, Photo.deleted_at.is_(None))):
        _soft_delete(p)


def can_view(db: Session, user: AppUser | None, p: Photo, is_admin: bool = False) -> bool:
    if p.deleted_at is not None:
        return False
    if is_admin or (user is not None and p.user_id == user.id):
        return True
    # 테스트 사용자 사진은 다른 사람에게 보이지 않는다 (SHOW_TEST_DATA=true 제외)
    if not get_settings().show_test_data:
        owner = db.get(AppUser, p.user_id)
        if owner is not None and owner.is_test:
            return False
    if p.post_id is not None:
        post = db.get(Post, p.post_id)
        return post is not None and post.deleted_at is None and not post.hidden
    if p.journal_id is not None:
        # 인증 완료 일지를 공개 글로 공유했을 때만 그 일지 사진을 다른 사람이 볼 수 있다
        j = db.get(Journal, p.journal_id)
        if j is None or j.deleted_at is not None or j.verification_status != VerificationStatus.APPROVED:
            return False
        shared = db.scalar(
            select(Post.id).where(Post.journal_id == j.id, Post.deleted_at.is_(None), Post.hidden.is_(False))
        )
        return shared is not None
    return False


def file_path(p: Photo) -> Path:
    path = (media_root() / p.path).resolve()
    if media_root() not in path.parents or not path.exists():
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다")
    return path
