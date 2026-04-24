"""Add welcome_sent flag to groups for one-time onboarding message.

Revision ID: 011
Revises: 010
Create Date: 2026-04-25
"""

import sqlalchemy as sa

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "groups",
        sa.Column(
            "welcome_sent",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Existing groups have already been interacting with the bot — don't spam them.
    op.execute("UPDATE groups SET welcome_sent = true")


def downgrade() -> None:
    op.drop_column("groups", "welcome_sent")
