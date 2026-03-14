"""Initial schema — all MVP tables.

Revision ID: 001
Revises:
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # groups
    op.create_table(
        "groups",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("wa_jid", sa.Text, unique=True, nullable=False),
        sa.Column("name_encrypted", sa.LargeBinary, nullable=True),
        sa.Column("timezone", sa.Text, server_default="UTC"),
        sa.Column("language", sa.Text, server_default="en"),
        sa.Column("settings", JSONB, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    # members
    op.create_table(
        "members",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "group_id",
            UUID,
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("wa_id_hash", sa.Text, nullable=False),
        sa.Column("wa_id_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("group_id", "wa_id_hash"),
    )

    # expenses
    op.create_table(
        "expenses",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "group_id",
            UUID,
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payer_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.Text, server_default="EUR"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("split_type", sa.Text, server_default="even"),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    # expense_participants
    op.create_table(
        "expense_participants",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "expense_id",
            UUID,
            sa.ForeignKey("expenses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("share_cents", sa.Integer, nullable=False),
    )

    # settlements
    op.create_table(
        "settlements",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "group_id",
            UUID,
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payer_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("payee_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    # reminders
    op.create_table(
        "reminders",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "group_id",
            UUID,
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("trigger_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recurrence", sa.Text, nullable=True),
        sa.Column("status", sa.Text, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    # itinerary_items
    op.create_table(
        "itinerary_items",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "group_id",
            UUID,
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_type", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.Text, nullable=True),
        sa.Column("location_url", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    # injection_log
    op.create_table(
        "injection_log",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "group_id",
            UUID,
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_hash", sa.Text, nullable=False),
        sa.Column("layer", sa.Text, nullable=False),
        sa.Column("risk_score", sa.Float, nullable=True),
        sa.Column(
            "flagged_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    # Indexes
    op.create_index(
        "idx_expenses_group",
        "expenses",
        ["group_id"],
        postgresql_where=sa.text("NOT is_deleted"),
    )
    op.create_index(
        "idx_reminders_pending",
        "reminders",
        ["trigger_at", "status"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("idx_itinerary_group", "itinerary_items", ["group_id", "start_at"])
    op.create_index("idx_injection_log_user", "injection_log", ["user_hash", "flagged_at"])


def downgrade() -> None:
    op.drop_index("idx_injection_log_user")
    op.drop_index("idx_itinerary_group")
    op.drop_index("idx_reminders_pending")
    op.drop_index("idx_expenses_group")
    op.drop_table("injection_log")
    op.drop_table("itinerary_items")
    op.drop_table("reminders")
    op.drop_table("settlements")
    op.drop_table("expense_participants")
    op.drop_table("expenses")
    op.drop_table("members")
    op.drop_table("groups")
