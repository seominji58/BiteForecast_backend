"""전국 낚시 탐험 도장: challenge_visit

Revision ID: 0012_challenge_visit
Revises: 0011_push
Create Date: 2026-11-26

- 새 표만 만든다. 기존 표·자료는 건드리지 않는다
"""
from collections.abc import Sequence

import sqlalchemy as sa

import app.models.base  # noqa: F401  UTCDateTime
from alembic import op

revision: str = '0012_challenge_visit'
down_revision: str | Sequence[str] | None = '0011_push'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'challenge_visit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('app_user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('place_id', sa.Integer(), sa.ForeignKey('place.id'), nullable=False),
        sa.Column('season', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('visited_at', app.models.base.UTCDateTime(), nullable=False),
        sa.Column('within_m', sa.Integer(), nullable=False),
    )
    op.create_index('ix_challenge_visit_user_id', 'challenge_visit', ['user_id'], unique=False)
    op.create_index('ix_challenge_visit_place_id', 'challenge_visit', ['place_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_challenge_visit_place_id', table_name='challenge_visit')
    op.drop_index('ix_challenge_visit_user_id', table_name='challenge_visit')
    op.drop_table('challenge_visit')
