"""기상청 중기해상예보 표 (4~10일 뒤 해역별 파고 범위·날씨)

Revision ID: 0007_mid_sea_forecast
Revises: 0006_species_flounder_drum
Create Date: 2026-11-17

- 새 표만 만든다. 기존 표·자료는 건드리지 않는다
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.base  # noqa: F401  UTCDateTime

revision: str = '0007_mid_sea_forecast'
down_revision: Union[str, Sequence[str], None] = '0006_species_flounder_drum'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'mid_sea_forecast',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('region', sa.String(length=20), nullable=False),
        sa.Column('tm_fc', app.models.base.UTCDateTime(), nullable=False),
        sa.Column('target_date', sa.String(length=10), nullable=False),
        sa.Column('period', sa.String(length=4), nullable=False),
        sa.Column('wave_min', sa.Float(), nullable=True),
        sa.Column('wave_max', sa.Float(), nullable=True),
        sa.Column('weather', sa.String(length=30), nullable=True),
        sa.Column('fetched_at', app.models.base.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('region', 'tm_fc', 'target_date', 'period'),
    )
    op.create_index(op.f('ix_mid_sea_forecast_region'), 'mid_sea_forecast', ['region'], unique=False)
    op.create_index(op.f('ix_mid_sea_forecast_tm_fc'), 'mid_sea_forecast', ['tm_fc'], unique=False)
    op.create_index(op.f('ix_mid_sea_forecast_target_date'), 'mid_sea_forecast', ['target_date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_mid_sea_forecast_target_date'), table_name='mid_sea_forecast')
    op.drop_index(op.f('ix_mid_sea_forecast_tm_fc'), table_name='mid_sea_forecast')
    op.drop_index(op.f('ix_mid_sea_forecast_region'), table_name='mid_sea_forecast')
    op.drop_table('mid_sea_forecast')
