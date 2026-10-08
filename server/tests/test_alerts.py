"""운영자 알림: 끊김 1번, 복구 1번, 야간·오래된 끊김은 알림 안 함"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.models.base import Base
from app.models.store import Store, Agent
from app.services import alerts

KST = timezone(timedelta(hours=9))


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    f = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with f() as s:
        s.add(Store(id=1, name="가게", store_code="A1"))
        await s.commit()
        yield s
    alerts._alerted.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_offline_then_recover(db):
    noon = datetime(2026, 10, 9, 12, 0, tzinfo=KST)
    agent = Agent(store_id=1, last_heartbeat_at=(noon - timedelta(minutes=45)).astimezone(timezone.utc))
    db.add(agent)
    await db.commit()

    assert any("끊김" in m for m in await alerts.check_agents(db, noon))
    assert await alerts.check_agents(db, noon + timedelta(minutes=10)) == []      # 반복 안 함

    agent.last_heartbeat_at = (noon + timedelta(minutes=20)).astimezone(timezone.utc)
    await db.commit()
    assert any("복구" in m for m in await alerts.check_agents(db, noon + timedelta(minutes=21)))


@pytest.mark.asyncio
async def test_no_alert_at_night_or_long_dead(db):
    night = datetime(2026, 10, 9, 2, 0, tzinfo=KST)
    db.add(Agent(store_id=1, last_heartbeat_at=(night - timedelta(hours=1)).astimezone(timezone.utc)))
    await db.commit()
    assert await alerts.check_agents(db, night) == []
    noon = datetime(2026, 10, 12, 12, 0, tzinfo=KST)   # 3일째 꺼짐
    assert await alerts.check_agents(db, noon) == []
