"""Re-own the reminders.recurrence column for the recurring-reminder feature.

The column was created in 001_initial_schema but never used. This migration
drops it and re-adds it so the recurrence feature has a single, traceable
origin in migration history.

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
    op.drop_column("reminders", "recurrence")
    op.add_column(
        "reminders",
        sa.Column("recurrence", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reminders", "recurrence")
    op.add_column(
        "reminders",
        sa.Column("recurrence", sa.Text(), nullable=True),
    )
