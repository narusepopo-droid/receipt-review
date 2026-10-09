"""광고토대왕 통합 계정 서버 (플레이스마스터 PRO + 영수증리뷰)"""
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app import licensing, orders
from app.config import settings
from app.db import SessionLocal, engine
from app.models import Base
from app.notify import send_sms
from app.routers import api, auth, my, ops
from app.seed import seed
from app.web import render, url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("account")
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


async def job_expiry():
    async with SessionLocal() as db:
        logger.info("expiry job: %s", await licensing.run_expiry_jobs(db, send_sms))


async def job_autopay():
    if not settings.toss_enabled:
        return
    async with SessionLocal() as db:
        logger.info("autopay job: %s", await orders.run_autopay(db, send_sms))


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        await seed(db)
    scheduler.add_job(job_expiry, "cron", hour=10, minute=0, id="expiry")      # 알림은 오전 10시
    scheduler.add_job(job_autopay, "cron", hour="9,15", minute=0, id="autopay")
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="플레이스 마스터 계정", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, session_cookie="acct_session",
                   max_age=60 * 60 * 12, same_site="lax", https_only=settings.SESSION_HTTPS_ONLY)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

for r in (auth.router, my.router, ops.router, api.router):
    app.include_router(r)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code in (301, 302, 303, 307) and exc.headers and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], status_code=exc.status_code)
    if request.url.path.startswith(("/api/", "/internal/")) or "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"ok": False, "message": exc.detail}, status_code=exc.status_code)
    msg = {404: "페이지를 찾을 수 없습니다", 403: "접근 권한이 없습니다"}.get(exc.status_code, str(exc.detail))
    if exc.status_code == 400 and isinstance(exc.detail, str):
        msg = exc.detail
    resp = render(request, "error.html", code=exc.status_code, message=msg)
    resp.status_code = exc.status_code
    return resp


@app.get("/")
async def home(request: Request):
    """첫 화면은 placemaster.co.kr (슬라이드). 로그인한 사람은 마이페이지로"""
    from app.db import SessionLocal as _S
    from app.web import current_account
    async with _S() as db:
        acc = await current_account(request, db)
    if acc:
        return RedirectResponse(url("/ops" if acc.is_operator else "/my"), status_code=303)
    return RedirectResponse(settings.SITE_URL, status_code=303)


@app.get("/health")
async def health():
    return {"ok": True}
