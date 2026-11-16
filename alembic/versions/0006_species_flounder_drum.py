"""어종 기준표에 도다리·점성어 추가 (데이터만, 표 구조 변경 없음)

Revision ID: 0006_species_flounder_drum
Revises: 0005_account_identity
Create Date: 2026-11-16

- 낚시터 공공데이터(place_info.species)에 도다리 37곳·점성어 8곳이 나오는데 기준표에 없어서
  기록·글에서 정식 어종으로 고를 수 없었다
- 있으면 건너뛴다 (여러 번 실행해도 같음). 되돌리기는 이 두 어종을 쓰는 기록·글이 없을 때만 지운다
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0006_species_flounder_drum'
down_revision: Union[str, Sequence[str], None] = '0005_account_identity'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW = [("marbled_flounder", "도다리(문치가자미)"), ("red_drum", "점성어")]


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
                "SELECT 1 FROM journal WHERE species_code = :c UNION ALL SELECT 1 FROM post WHERE species_code = :c LIMIT 1"
            ),
            {"c": code},
        ).first()
        if not used:
            conn.execute(sa.text("DELETE FROM species WHERE code = :c"), {"c": code})
