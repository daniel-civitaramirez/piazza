"""Add checklist_items table.

Revision ID: 010
Revises: 009
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "checklist_items",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("group_id", UUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("list_name", sa.LargeBinary, nullable=False),
        sa.Column("is_done", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_checklist_group", "checklist_items", ["group_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_checklist_group", table_name="checklist_items")
    op.drop_table("checklist_items")
