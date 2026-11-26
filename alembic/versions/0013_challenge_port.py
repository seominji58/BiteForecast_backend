"""탐험 배낚시 항구 시즌: challenge_visit.port_key 추가, place_id 비워도 됨

Revision ID: 0013_challenge_port
Revises: 0012_challenge_visit
Create Date: 2026-11-26

- 열 하나 추가 + place_id NULL 허용. 기존 행은 그대로
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0013_challenge_port'
down_revision: str | Sequence[str] | None = '0012_challenge_visit'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('challenge_visit') as b:
        b.add_column(sa.Column('port_key', sa.String(length=80), nullable=True))
        b.alter_column('place_id', existing_type=sa.Integer(), nullable=True)
    op.create_index('ix_challenge_visit_port_key', 'challenge_visit', ['port_key'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_challenge_visit_port_key', table_name='challenge_visit')
    with op.batch_alter_table('challenge_visit') as b:
        b.alter_column('place_id', existing_type=sa.Integer(), nullable=False)
        b.drop_column('port_key')
