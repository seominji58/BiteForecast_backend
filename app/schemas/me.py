from pydantic import BaseModel


class TitleInfo(BaseModel):
    name: str
    min_points: int


class MyTitleOut(BaseModel):
    total_points: int
    current: TitleInfo
    next: TitleInfo | None  # None = 최고 칭호
    points_to_next: int | None
