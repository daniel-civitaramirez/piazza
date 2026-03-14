"""Add approval_status column to groups table.

Revision ID: 005
Revises: 004
Create Date: 2026-03-15
"""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "groups",
        sa.Column(
            "approval_status",
            sa.Text,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )
    # Existing groups should not be retroactively blocked
    op.execute("UPDATE groups SET approval_status = 'approved'")

    op.create_index(
        "idx_groups_pending",
        "groups",
        ["approval_status"],
        postgresql_where=sa.text("approval_status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("idx_groups_pending", table_name="groups")
    op.drop_column("groups", "approval_status")
