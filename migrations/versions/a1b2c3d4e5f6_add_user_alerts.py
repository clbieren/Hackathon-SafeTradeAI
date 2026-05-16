"""Add user_alerts table

Revision ID: a1b2c3d4e5f6
Revises: 59a1a9df1ef5
Create Date: 2026-05-15 14:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '59a1a9df1ef5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create user_alerts table."""
    op.create_table(
        'user_alerts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column('company_name', sa.String(length=255), nullable=False),
        sa.Column('full_address', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_alerts_user_id', 'user_alerts', ['user_id'], unique=False)
    op.create_index(
        'ix_user_alerts_next_run_at_active',
        'user_alerts',
        ['next_run_at', 'is_active'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema: drop user_alerts table."""
    op.drop_index('ix_user_alerts_next_run_at_active', table_name='user_alerts')
    op.drop_index('ix_user_alerts_user_id', table_name='user_alerts')
    op.drop_table('user_alerts')
