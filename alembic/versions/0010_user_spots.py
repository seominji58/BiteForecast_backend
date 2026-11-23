"""내 낚시터: user_spot (사용자가 지도에 직접 찍은 비공개 포인트)

Revision ID: 0010_user_spots
Revises: 0009_species_more
Create Date: 2026-11-23

- 새 표만 만든다. 기존 표·자료는 건드리지 않는다
"""
from collections.abc import Sequence

import sqlalchemy as sa

import app.models.base  # noqa: F401  UTCDateTime
from alembic import op

revision: str = '0010_user_spots'
down_revision: str | Sequence[str] | None = '0009_species_more'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'user_spot',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('app_user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lon', sa.Float(), nullable=False),
        sa.Column('memo', sa.String(length=500), nullable=True),
        sa.Column('created_at', app.models.base.UTCDateTime(), nullable=False),
    )
    op.create_index('ix_user_spot_user_id', 'user_spot', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_user_spot_user_id', table_name='user_spot')
    op.drop_table('user_spot')
