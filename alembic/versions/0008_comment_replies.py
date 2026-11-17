"""대댓글: comment.parent_id (원댓글 id, 한 단계만)

Revision ID: 0008_comment_replies
Revises: 0007_mid_sea_forecast
Create Date: 2026-11-17

- 칸 하나만 더한다 (비어 있어도 됨). 기존 댓글·글은 건드리지 않는다 (모두 원댓글로 남음)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0008_comment_replies'
down_revision: Union[str, Sequence[str], None] = '0007_mid_sea_forecast'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('comment') as b:
        b.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_comment_parent_id', 'comment', ['parent_id'], ['id'], ondelete='CASCADE')
        b.create_index('ix_comment_parent_id', ['parent_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('comment') as b:
        b.drop_index('ix_comment_parent_id')
        b.drop_constraint('fk_comment_parent_id', type_='foreignkey')
        b.drop_column('parent_id')
