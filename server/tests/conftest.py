"""pytest 설정 및 fixtures"""
import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.models.base import Base


@pytest.fixture(scope="session")
def event_loop():
    """세션 범위 이벤트 루프"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session():
    """테스트용 인메모리 DB 세션"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()
