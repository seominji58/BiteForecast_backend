"""커뮤니티 운영: 사용자 차단 · 신고 검토 시각 · 공유 기록 채비 표시

Revision ID: 0004_block_report_review_tackle
Revises: 0003_post_location_visibility
Create Date: 2026-11-16

- user_block: 차단한 사람에게 차단된 사람의 글·댓글을 숨긴다
- content_report.reviewed_at: 관리자가 검토한 신고는 자동 숨김 기준에서 뺀다
- post.show_tackle: 공유 기록의 미끼·채비 표시 여부. 기존 글은 동의 전이므로 false
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.base  # noqa: F401  UTCDateTime

revision: str = '0004_block_report_review_tackle'
down_revision: Union[str, Sequence[str], None] = '0003_post_location_visibility'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_block',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('blocked_user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', app.models.base.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['blocked_user_id'], ['app_user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'blocked_user_id'),
    )
    op.add_column('content_report', sa.Column('reviewed_at', app.models.base.UTCDateTime(), nullable=True))
    op.add_column('post', sa.Column('show_tackle', sa.Boolean(), server_default='0', nullable=False))
    # Supabase: 새 표도 공개 역할(anon·authenticated)이 접근하지 못하게 (역할이 있는 DB 에서만)
    if op.get_bind().dialect.name == 'postgresql':
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON TABLE public.user_block FROM anon, authenticated;
              END IF;
            END $$;
            """
        )
        op.execute('ALTER TABLE public.user_block ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_column('post', 'show_tackle')
    op.drop_column('content_report', 'reviewed_at')
    op.drop_table('user_block')
