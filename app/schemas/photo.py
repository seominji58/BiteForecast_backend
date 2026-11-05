from pydantic import BaseModel


class PhotoOut(BaseModel):
    id: int
    # API 기준 상대 경로 (예: "/photos/12"). 앱은 API 주소 뒤에 붙이고 X-Device-Id 헤더로 요청한다
    url: str
    width: int
    height: int
