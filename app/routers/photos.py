from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession, OptionalUser, is_admin_token
from app.core.config import get_settings
from app.models import Photo
from app.models.enums import PhotoPurpose
from app.schemas.photo import PhotoOut
from app.services import photos as svc

router = APIRouter(prefix="/photos", tags=["photos"])


@router.post("", response_model=PhotoOut, status_code=status.HTTP_201_CREATED)
async def upload_photo(
    user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    purpose: Annotated[PhotoPurpose, Form()],
    taken_at: Annotated[datetime | None, Form()] = None,
):
    """사진 1장 업로드 (EXIF·위치 제거 후 저장). 일지·글 저장 시 photo_ids 로 연결한다.

    purpose: journal(인증용 낚시일지 사진) / post(일반 게시글 사진, 포인트 무관)
    taken_at: 기기에서 읽은 촬영 시각(선택). 파일 EXIF 가 있으면 그쪽을 쓴다 — 검토 참고용
    """
    limit = get_settings().photo_max_bytes
    raw = await file.read(limit + 1)
    if taken_at is not None and taken_at.tzinfo is None:
        taken_at = None
    photo = svc.save_upload(db, user, purpose, raw, taken_at)
    return svc.photo_out(photo)


@router.get("/{photo_id}")
def get_photo(
    photo_id: int,
    db: DbSession,
    user: OptionalUser,
    x_admin_token: Annotated[str | None, Header()] = None,
):
    """사진 파일. 본인 사진, 공개된 글의 사진, 관리자만 볼 수 있다 (그 외에는 존재 여부도 숨김)"""
    p = db.get(Photo, photo_id)
    if p is None or not svc.can_view(db, user, p, is_admin=is_admin_token(x_admin_token)):
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다")
    return FileResponse(
        svc.file_path(p), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"}
    )
