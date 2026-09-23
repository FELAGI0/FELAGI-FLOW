"""add restrict on workspaces.created_by

Revision ID: b94a22d009ba
Revises: 5eb7c7d26b51
Create Date: 2026-09-23 21:40:11.211935

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b94a22d009ba'
down_revision: Union[str, None] = '5eb7c7d26b51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("workspaces_created_by_fkey", "workspaces", type_="foreignkey")
    op.create_foreign_key(
        "workspaces_created_by_fkey",
        "workspaces",
        "users",
        ["created_by"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("workspaces_created_by_fkey", "workspaces", type_="foreignkey")
    op.create_foreign_key(
        "workspaces_created_by_fkey", "workspaces", "users", ["created_by"], ["id"]
    )
