"""Add notes table.

Revision ID: 002
Revises: 001
Create Date: 2026-03-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notes",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("group_id", UUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tag", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_notes_group", "notes", ["group_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_notes_group", table_name="notes")
    op.drop_table("notes")
