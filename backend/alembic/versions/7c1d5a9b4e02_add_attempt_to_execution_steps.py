"""add attempt to execution_steps

Revision ID: 7c1d5a9b4e02
Revises: 941bceee1ad2
Create Date: 2026-09-25 01:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7c1d5a9b4e02'
down_revision: Union[str, None] = '941bceee1ad2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default обязателен: без него add_column на непустой таблице падает,
    # т.к. существующие строки не получают значение для NOT NULL. Историческим
    # шагам проставляется 1 — до 4.C повторов узла не существовало.
    op.add_column(
        'execution_steps',
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
    )


def downgrade() -> None:
    op.drop_column('execution_steps', 'attempt')