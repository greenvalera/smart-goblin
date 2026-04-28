"""add_parent_set_code_to_sets

Revision ID: b3e8d2a17c45
Revises: af412fc86ff3
Create Date: 2026-04-27 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e8d2a17c45'
down_revision: Union[str, None] = 'af412fc86ff3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'sets',
        sa.Column('parent_set_code', sa.String(length=10), nullable=True),
    )
    op.create_foreign_key(
        'fk_sets_parent_set_code',
        'sets',
        'sets',
        ['parent_set_code'],
        ['code'],
        ondelete='SET NULL',
    )
    op.create_check_constraint(
        'ck_sets_parent_not_self',
        'sets',
        'parent_set_code IS NULL OR parent_set_code != code',
    )
    op.create_index(
        'ix_sets_parent_set_code',
        'sets',
        ['parent_set_code'],
    )


def downgrade() -> None:
    op.drop_index('ix_sets_parent_set_code', table_name='sets')
    op.drop_constraint('ck_sets_parent_not_self', 'sets', type_='check')
    op.drop_constraint('fk_sets_parent_set_code', 'sets', type_='foreignkey')
    op.drop_column('sets', 'parent_set_code')
