"""FastAPI 애플리케이션 진입점"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.db import engine, async_session_factory
from app.models.base import Base
from app.routers import agent, customer, admin, ops, download, auth
from app.services.disposal import dispose_expired_receipts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()
scheduler = AsyncIOScheduler()


async def run_disposal_job():
    async with async_session_factory() as session:
        try:
            await dispose_expired_receipts(session)
        except Exception as e:
            logger.error(f"Disposal job failed: {e}")


async def run_sms_job():
    from app.services.sms import run_due_campaigns
    async with async_session_factory() as session:
        try:
            await run_due_campaigns(session)
        except Exception as e:
            logger.error(f"SMS job failed: {e}")


async def run_alert_job():
    from app.services.alerts import check_agents
    async with async_session_factory() as session:
        try:
            await check_agents(session)
        except Exception as e:
            logger.error(f"Alert job failed: {e}")


async def ensure_schema():
    """없는 테이블만 생성 + 모델과 DB 칼럼 차이 경고 (기존 테이블은 변경하지 않음)"""
    from sqlalchemy import inspect
    from app.db import engine
    import app.models  # noqa: F401  모든 모델 등록
    from app.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, checkfirst=True))

        def drift(c):
            insp = inspect(c)
            out = []
            for table in Base.metadata.sorted_tables:
                if not insp.has_table(table.name):
                    continue
                have = {col["name"] for col in insp.get_columns(table.name)}
                missing = [col.name for col in table.columns if col.name not in have]
                if missing:
                    out.append(f"{table.name}: {missing}")
            return out
        for line in await conn.run_sync(drift):
            logger.warning(f"DB 칼럼 누락 (마이그레이션 필요) {line}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await ensure_schema()
    except Exception as e:
        logger.error(f"Schema check failed: {e}")

    scheduler.add_job(
        run_disposal_job,
        IntervalTrigger(minutes=30),
        id="disposal",
        replace_existing=True
    )
    scheduler.add_job(
        run_alert_job,
        IntervalTrigger(minutes=10),
        id="alerts",
        replace_existing=True
    )
    scheduler.add_job(
        run_sms_job,
        IntervalTrigger(minutes=1),
        id="sms",
        replace_existing=True
    )
    scheduler.start()
    logger.info("Scheduler started")

    yield

    scheduler.shutdown()
    logger.info("Scheduler stopped")


app = FastAPI(
    title="영수증리뷰 API",
    description="포스 영수증 캡처 및 리뷰 자동화 서비스",
    version="0.1.0",
    lifespan=lifespan
)

# CORS 미들웨어 (외부 사이트에서 API 호출 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 세션 미들웨어 (점주·운영자 로그인, 12시간 유지)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    max_age=settings.SESSION_MAX_AGE,
    https_only=settings.SESSION_HTTPS_ONLY,
    same_site="lax",
)

app.include_router(auth.router)
app.include_router(agent.router)
app.include_router(customer.router)
app.include_router(admin.router)
app.include_router(ops.router)
app.include_router(download.router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")


@app.get("/")
async def root():
    return {"message": "영수증리뷰 API", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
