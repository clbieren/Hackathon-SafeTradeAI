"""Initial migration

Revision ID: 59a1a9df1ef5
Revises: 
Create Date: 2026-05-13 19:23:16.178383

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '59a1a9df1ef5'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create users, companies, and reports tables."""
    # users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('company_name', sa.String(length=255), nullable=True),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # companies table
    op.create_table(
        'companies',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('tax_number', sa.String(length=50), nullable=False),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tax_number')
    )
    op.create_index(op.f('ix_companies_name'), 'companies', ['name'], unique=False)
    op.create_index(op.f('ix_companies_owner_id'), 'companies', ['owner_id'], unique=False)

    # reports table
    op.create_table(
        'reports',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('trust_score', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('risk_summary', sa.Text(), nullable=True),
        sa.Column('market_data', sa.Text(), nullable=True),
        sa.Column('official_records', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Faz-1 yasal röntgen verisi. Anahtarlar: gib_status, mersis_data, kik_ban, tsg_records'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reports_company_id'), 'reports', ['company_id'], unique=False)
    op.create_index(op.f('ix_reports_owner_id'), 'reports', ['owner_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema: drop tables in reverse order."""
    op.drop_index(op.f('ix_reports_owner_id'), table_name='reports')
    op.drop_index(op.f('ix_reports_company_id'), table_name='reports')
    op.drop_table('reports')
    op.drop_index(op.f('ix_companies_owner_id'), table_name='companies')
    op.drop_index(op.f('ix_companies_name'), table_name='companies')
    op.drop_table('companies')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
