"""소셜 로그인 수단 표 (구글·카카오, 이후 네이버)

Revision ID: 0005_account_identity
Revises: 0004_block_report_review_tackle
Create Date: 2026-11-16

- account_identity: (provider, subject) 하나에 계정 하나, 계정 하나에 제공자별 하나
- 기존 구글 계정(account.google_sub)을 provider='google' 줄로 옮긴다
- account.google_sub 칸은 되돌리기 쉽게 이번에는 남긴다 (다음 마이그레이션에서 정리)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.base  # noqa: F401  UTCDateTime

revision: str = '0005_account_identity'
down_revision: Union[str, Sequence[str], None] = '0004_block_report_review_tackle'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'account_identity',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=16), nullable=False),
        sa.Column('subject', sa.String(length=128), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=True),
        sa.Column('last_login_at', app.models.base.UTCDateTime(), nullable=True),
        sa.Column('created_at', app.models.base.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'subject'),
        sa.UniqueConstraint('account_id', 'provider'),
    )
    op.create_index(op.f('ix_account_identity_account_id'), 'account_identity', ['account_id'], unique=False)
    # 기존 구글 계정 옮기기 (탈퇴 계정은 google_sub 가 이미 비어 있다)
    op.execute(
        """
        INSERT INTO account_identity (account_id, provider, subject, email, last_login_at, created_at)
        SELECT id, 'google', google_sub, email, last_login_at, created_at
        FROM account WHERE google_sub IS NOT NULL AND deleted_at IS NULL
        """
    )
    if op.get_bind().dialect.name == 'postgresql':
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON TABLE public.account_identity FROM anon, authenticated;
              END IF;
            END $$;
            """
        )
        op.execute('ALTER TABLE public.account_identity ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index(op.f('ix_account_identity_account_id'), table_name='account_identity')
    op.drop_table('account_identity')
