"""Shared test fixtures."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from piazza.core.encryption import encrypt, hash_phone
from piazza.db.models.group import Group
from piazza.db.models.member import Member


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# A fixed 32-byte key for deterministic test encryption
TEST_ENCRYPTION_KEY = b"\x00" * 32
TEST_ENCRYPTION_KEY_B64 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Ensure encryption_key is always set in tests."""
    from piazza.config.settings import settings

    monkeypatch.setattr(settings, "encryption_key", TEST_ENCRYPTION_KEY_B64)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async SQLAlchemy session backed by in-memory SQLite."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    import piazza.db.models  # noqa: F401
    from piazza.db.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
def redis_client():
    """Fake Redis instance for testing."""
    import fakeredis.aioredis

    return fakeredis.aioredis.FakeRedis()


@dataclass
class SampleGroup:
    """Container for a pre-seeded group with members."""

    group: Group
    alice: Member
    bob: Member
    charlie: Member

    @property
    def group_id(self) -> uuid.UUID:
        return self.group.id

    @property
    def member_ids(self) -> list[uuid.UUID]:
        return [self.alice.id, self.bob.id, self.charlie.id]


@pytest_asyncio.fixture
async def sample_group(db_session: AsyncSession) -> SampleGroup:
    """Pre-created group with 3 members: Alice, Bob, Charlie."""
    group = Group(wa_jid="120363001@g.us", timezone="UTC", approval_status="approved")
    db_session.add(group)
    await db_session.flush()

    members = []
    for name, phone in [
        ("Alice", "5511111111111@s.whatsapp.net"),
        ("Bob", "5522222222222@s.whatsapp.net"),
        ("Charlie", "5533333333333@s.whatsapp.net"),
    ]:
        m = Member(
            group_id=group.id,
            wa_id_hash=hash_phone(phone),
            wa_id_encrypted=encrypt(phone, TEST_ENCRYPTION_KEY),
            display_name=encrypt(name, TEST_ENCRYPTION_KEY),
        )
        db_session.add(m)
        members.append(m)

    await db_session.flush()
    return SampleGroup(group=group, alice=members[0], bob=members[1], charlie=members[2])
