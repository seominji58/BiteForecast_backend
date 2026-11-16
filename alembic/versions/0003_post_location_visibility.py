"""커뮤니티 글 위치 공개 범위 (낚시터 이름 / 지역만 / 숨김) + 낚시터 없이 고른 지역

Revision ID: 0003_post_location_visibility
Revises: 0002_trip_members
Create Date: 2026-11-16

- 기존 글은 낚시터를 공개한 상태로 올라갔으므로 location_visibility='place' 로 채운다 (공개 범위를 바꾸지 않음)
- 새 열만 더하고 기존 값은 바꾸지 않는다
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0003_post_location_visibility'
down_revision: Union[str, Sequence[str], None] = '0002_trip_members'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'post',
        sa.Column(
            'location_visibility',
            sa.Enum('place', 'region', 'hidden', name='locationvisibility', native_enum=False, length=32),
            server_default='place',
            nullable=False,
        ),
    )
    op.add_column('post', sa.Column('region_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_post_region_id', 'post', 'region', ['region_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_post_region_id', 'post', type_='foreignkey')
    op.drop_column('post', 'region_id')
    op.drop_column('post', 'location_visibility')
