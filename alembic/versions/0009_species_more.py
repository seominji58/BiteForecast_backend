"""어종 기준표에 바다낚시 어종 7종 추가 (데이터만, 표 구조 변경 없음)

Revision ID: 0009_species_more
Revises: 0008_comment_replies
Create Date: 2026-11-23

- 통계청 어업생산동향조사로 「어획 많은 달」을 계산한 어종 중 앱에 없던 것:
  삼치·방어·쥐치·한치·전어·가자미·민어
- 있으면 건너뛴다. 되돌리기는 그 어종을 쓰는 기록·글이 없을 때만 지운다
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_species_more"
down_revision: Union[str, Sequence[str], None] = "0008_comment_replies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW = [
    ("spanish_mackerel", "삼치"),
    ("yellowtail", "방어"),
    ("filefish", "쥐치"),
    ("mitre_squid", "한치"),
    ("gizzard_shad", "전어"),
    ("flounder", "가자미"),
    ("croaker", "민어"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for code, name in NEW:
        exists = conn.execute(sa.text("SELECT 1 FROM species WHERE code = :c"), {"c": code}).first()
        if not exists:
            conn.execute(sa.text("INSERT INTO species (code, name_ko) VALUES (:c, :n)"), {"c": code, "n": name})


def downgrade() -> None:
    conn = op.get_bind()
    for code, _ in NEW:
        used = conn.execute(
            sa.text(
                "SELECT 1 FROM journal WHERE species_code = :c "
                "UNION ALL SELECT 1 FROM post WHERE species_code = :c LIMIT 1"
            ),
            {"c": code},
        ).first()
        if not used:
            conn.execute(sa.text("DELETE FROM species WHERE code = :c"), {"c": code})
