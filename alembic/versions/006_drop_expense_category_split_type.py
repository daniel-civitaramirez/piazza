"""Drop unused category and split_type columns from expenses table.

Revision ID: 006
Revises: 005
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("expenses", "category")
    op.drop_column("expenses", "split_type")


def downgrade() -> None:
    op.add_column(
        "expenses",
        sa.Column("split_type", sa.Text, nullable=False, server_default=sa.text("'even'")),
    )
    op.add_column(
        "expenses",
        sa.Column("category", sa.Text, nullable=True),
    )
