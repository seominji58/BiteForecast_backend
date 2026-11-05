from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.journal import JournalIn, JournalMutationOut, JournalOut
from app.services import journals as svc

router = APIRouter(prefix="/journals", tags=["journals"])


@router.get("", response_model=list[JournalOut])
def list_journals(user: CurrentUser, db: DbSession):
    return svc.list_journals(db, user)


@router.post("", response_model=JournalMutationOut, status_code=status.HTTP_201_CREATED)
def create_journal(data: JournalIn, user: CurrentUser, db: DbSession):
    return svc.create_journal(db, user, data)


@router.get("/{journal_id}", response_model=JournalOut)
def get_journal(journal_id: int, user: CurrentUser, db: DbSession):
    return svc.to_out(db, svc.get_owned(db, user, journal_id))


@router.put("/{journal_id}", response_model=JournalMutationOut)
def update_journal(journal_id: int, data: JournalIn, user: CurrentUser, db: DbSession):
    return svc.update_journal(db, user, journal_id, data)


@router.delete("/{journal_id}", response_model=JournalMutationOut)
def delete_journal(journal_id: int, user: CurrentUser, db: DbSession):
    return svc.delete_journal(db, user, journal_id)


@router.post("/{journal_id}/verification", response_model=JournalOut)
def request_verification(journal_id: int, user: CurrentUser, db: DbSession):
    """사진 인증 신청 (사진 1장 이상·어종 필요). 포인트는 관리자 승인 후에만 지급"""
    return svc.request_verification(db, user, journal_id)


@router.delete("/{journal_id}/verification", response_model=JournalOut)
def cancel_verification(journal_id: int, user: CurrentUser, db: DbSession):
    """검토 대기 중인 인증 신청 취소"""
    return svc.cancel_verification(db, user, journal_id)
