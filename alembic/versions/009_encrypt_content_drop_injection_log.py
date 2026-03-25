"""Encrypt user content columns and drop injection_log table.

Revision ID: 009
Revises: 008
Create Date: 2026-03-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"


def _migrate_column(
    conn: sa.engine.Connection,
    key: bytes,
    table: str,
    column: str,
    nullable: bool,
) -> None:
    """Add encrypted LargeBinary column, migrate data, drop old, rename."""
    from piazza.core.encryption import encrypt

    temp = f"{column}_enc"
    op.add_column(table, sa.Column(temp, sa.LargeBinary, nullable=True))

    rows = conn.execute(
        sa.text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")  # noqa: S608
    )
    for row in rows:
        encrypted = encrypt(row[1], key)
        conn.execute(
            sa.text(f"UPDATE {table} SET {temp} = :enc WHERE id = :id"),  # noqa: S608
            {"enc": encrypted, "id": row[0]},
        )

    op.drop_column(table, column)
    op.alter_column(table, temp, new_column_name=column, nullable=nullable)


def upgrade() -> None:
    # 1. Drop injection_log table and its index
    op.drop_index("idx_injection_log_user", table_name="injection_log")
    op.drop_table("injection_log")

    # 2. Encrypt existing plaintext columns in-place
    conn = op.get_bind()
    from piazza.config.settings import settings

    key = settings.encryption_key_bytes

    columns = [
        ("expenses", "description", True),
        ("reminders", "message", False),
        ("itinerary_items", "title", False),
        ("itinerary_items", "location", True),
        ("itinerary_items", "notes", True),
        ("notes", "content", False),
        ("notes", "tag", True),
        ("message_log", "content", False),
        ("members", "display_name", False),
    ]
    for table, column, nullable in columns:
        _migrate_column(conn, key, table, column, nullable)


def downgrade() -> None:
    raise RuntimeError(
        "Irreversible migration: cannot convert encrypted data back to plaintext "
        "without an explicit decryption script."
    )
