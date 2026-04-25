"""Add reminders.recurrence column for the recurring-reminder feature.

The column was originally created in 001 as a stub, then dropped (unused)
in 007. This migration re-adds it for the recurring-reminder (RRULE) feature.

Revision ID: 012
Revises: 011
Create Date: 2026-04-25
"""

import sqlalchemy as sa

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reminders",
        sa.Column("recurrence", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reminders", "recurrence")
