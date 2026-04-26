"""Add settlements.currency.

Settlements stored a numeric amount with no unit, which is fine in a
single-currency world but breaks as soon as a group logs anything in a
non-default currency. Backfill existing rows to EUR (the historical
default at the time of this migration), then drop the server_default
so future inserts must supply the currency explicitly.

Revision ID: 013
Revises: 012
Create Date: 2026-04-26
"""

import sqlalchemy as sa

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

BACKFILL_CURRENCY = "EUR"


def upgrade() -> None:
    op.add_column(
        "settlements",
        sa.Column(
            "currency",
            sa.Text(),
            nullable=False,
            server_default=BACKFILL_CURRENCY,
        ),
    )
    op.alter_column("settlements", "currency", server_default=None)


def downgrade() -> None:
    op.drop_column("settlements", "currency")
