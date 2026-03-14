"""Group database queries."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.config.settings import settings
from piazza.db.models.group import Group


async def get_or_create_group(
    session: AsyncSession, group_jid: str
) -> tuple[Group, bool]:
    """Get or create a group by WhatsApp JID.

    Returns (group, was_created) where was_created is True if a new record
    was inserted.
    """
    result = await session.execute(
        select(Group).where(Group.wa_jid == group_jid)
    )
    group = result.scalar_one_or_none()
    if group is not None:
        return group, False

    approval = "approved" if not settings.admin_jid else "pending"
    group = Group(wa_jid=group_jid, approval_status=approval)
    session.add(group)
    await session.flush()
    return group, True
