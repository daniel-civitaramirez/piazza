"""Add is_active column to members table.

Revision ID: 003
Revises: 002
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "members",
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
    )
    op.create_index(
        "idx_members_group_active",
        "members",
        ["group_id"],
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("idx_members_group_active", table_name="members")
    op.drop_column("members", "is_active")
