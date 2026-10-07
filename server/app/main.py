"""FastAPI 애플리케이션 진입점"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.db import engine, async_session_factory
from app.models.base import Base
from app.routers import agent, customer, admin, ops, download
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        run_disposal_job,
        IntervalTrigger(minutes=30),
        id="disposal",
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
