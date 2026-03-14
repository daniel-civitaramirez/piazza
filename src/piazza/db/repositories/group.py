"""Group database queries."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.db.models.group import Group


async def get_or_create_group(session: AsyncSession, group_jid: str) -> Group:
    """Get or create a group by WhatsApp JID."""
    result = await session.execute(
        select(Group).where(Group.wa_jid == group_jid)
    )
    group = result.scalar_one_or_none()
    if group is not None:
        return group

    group = Group(wa_jid=group_jid)
    session.add(group)
    await session.flush()
    return group
