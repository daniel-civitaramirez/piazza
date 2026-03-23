"""Drop unused columns: location_url, language, last_active_at, recurrence.

Revision ID: 007
Revises: 006
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("itinerary_items", "location_url")
    op.drop_column("groups", "language")
    op.drop_column("groups", "last_active_at")
    op.drop_column("reminders", "recurrence")


def downgrade() -> None:
    op.add_column(
        "reminders",
        sa.Column("recurrence", sa.Text, nullable=True),
    )
    op.add_column(
        "groups",
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "groups",
        sa.Column("language", sa.Text, nullable=False, server_default=sa.text("'en'")),
    )
    op.add_column(
        "itinerary_items",
        sa.Column("location_url", sa.Text, nullable=True),
    )
