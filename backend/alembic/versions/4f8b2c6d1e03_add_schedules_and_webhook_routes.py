"""add schedules and webhook_routes

Revision ID: 4f8b2c6d1e03
Revises: 7c1d5a9b4e02
Create Date: 2026-09-25 22:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4f8b2c6d1e03'
down_revision: Union[str, None] = '7c1d5a9b4e02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('schedules',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('workflow_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('spec', sa.String(), nullable=False),
    sa.Column('node_id', sa.String(), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    # тик планировщика: enabled + next_run_at <= now()
    op.create_index('ix_schedules_enabled_next_run_at', 'schedules', ['enabled', 'next_run_at'], unique=False)

    op.create_table('webhook_routes',
    sa.Column('token', sa.String(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('workflow_id', sa.Uuid(), nullable=False),
    sa.Column('node_id', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token')
    )
    # sync при публикации ищет маршруты конкретного workflow
    op.create_index('ix_webhook_routes_workflow_id', 'webhook_routes', ['workflow_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_webhook_routes_workflow_id', table_name='webhook_routes')
    op.drop_table('webhook_routes')
    op.drop_index('ix_schedules_enabled_next_run_at', table_name='schedules')
    op.drop_table('schedules')