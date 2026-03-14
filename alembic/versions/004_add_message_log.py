"""Add message_log table for conversation history.

Revision ID: 004
Revises: 003
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_log",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("group_id", UUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", UUID, sa.ForeignKey("members.id"), nullable=True),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("wa_message_id", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_message_log_group_recent", "message_log", ["group_id", "created_at"])
    op.create_index("idx_message_log_wa_id", "message_log", ["wa_message_id"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_message_log_wa_id", table_name="message_log")
    op.drop_index("idx_message_log_group_recent", table_name="message_log")
    op.drop_table("message_log")
