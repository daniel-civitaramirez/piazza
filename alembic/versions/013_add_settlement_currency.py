"""Add settlements.currency.

Settlements stored a numeric amount with no unit, which is fine in a
single-currency world but breaks as soon as a group logs anything in a
non-default currency. Backfill existing rows to the configured default
currency, then enforce NOT NULL.

Revision ID: 013
Revises: 012
Create Date: 2026-04-26
"""

import sqlalchemy as sa

from alembic import op
from piazza.config.settings import settings

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settlements",
        sa.Column(
            "currency",
            sa.Text(),
            nullable=False,
            server_default=settings.default_currency,
        ),
    )


def downgrade() -> None:
    op.drop_column("settlements", "currency")
