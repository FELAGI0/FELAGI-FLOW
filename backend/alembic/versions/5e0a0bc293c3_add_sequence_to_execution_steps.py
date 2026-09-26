"""add sequence to execution_steps

Revision ID: 5e0a0bc293c3
Revises: 4f8b2c6d1e03
Create Date: 2026-09-26 14:09:07.620029

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5e0a0bc293c3'
down_revision: Union[str, None] = '4f8b2c6d1e03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default='0' — только чтобы заполнить существующие строки:
    # NOT NULL без дефолта не применится к непустой таблице.
    op.add_column(
        'execution_steps',
        sa.Column('sequence', sa.Integer(), nullable=False, server_default='0'),
    )
    # Бэкфилл: ранее порядок определялся (created_at, node_id) — тем же ключом
    # нумеруем старые строки в пределах запуска, начиная с 1.
    op.execute(
        """
        UPDATE execution_steps AS es
        SET sequence = sub.rn
        FROM (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY execution_id ORDER BY created_at, node_id
                   ) AS rn
            FROM execution_steps
        ) AS sub
        WHERE es.id = sub.id
        """
    )
    # Дефолт больше не нужен: sequence задаёт runner счётчиком.
    op.alter_column('execution_steps', 'sequence', server_default=None)


def downgrade() -> None:
    op.drop_column('execution_steps', 'sequence')