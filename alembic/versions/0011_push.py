"""푸시 알림: push_device · push_pref · push_log

Revision ID: 0011_push
Revises: 0010_user_spots
Create Date: 2026-11-25

- 새 표만 만든다. 기존 표·자료는 건드리지 않는다
"""
from collections.abc import Sequence

import sqlalchemy as sa

import app.models.base  # noqa: F401  UTCDateTime
from alembic import op

revision: str = '0011_push'
down_revision: str | Sequence[str] | None = '0010_user_spots'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'push_device',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('app_user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token', sa.String(length=512), nullable=False, unique=True),
        sa.Column('platform', sa.String(length=10), nullable=False),
        sa.Column('last_seen_at', app.models.base.UTCDateTime(), nullable=True),
        sa.Column('created_at', app.models.base.UTCDateTime(), nullable=False),
    )
    op.create_index('ix_push_device_user_id', 'push_device', ['user_id'], unique=False)
    op.create_table(
        'push_pref',
        sa.Column(
            'user_id', sa.Integer(), sa.ForeignKey('app_user.id', ondelete='CASCADE'), primary_key=True
        ),
        sa.Column('fav_good', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('trip_warning', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('weekly_best', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        'push_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('app_user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('key', sa.String(length=120), nullable=False),
        sa.Column('created_at', app.models.base.UTCDateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'kind', 'key'),
    )
    op.create_index('ix_push_log_user_id', 'push_log', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_push_log_user_id', table_name='push_log')
    op.drop_table('push_log')
    op.drop_table('push_pref')
    op.drop_index('ix_push_device_user_id', table_name='push_device')
    op.drop_table('push_device')
