"""화면 공통: 템플릿, 로그인 세션, 표시 형식"""
from datetime import timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app import licensing
from app.config import settings
from app.models import Account

KST = timezone(timedelta(hours=9))
templates = Jinja2Templates(directory="app/templates")


def url(path: str) -> str:
    return settings.BASE_PATH.rstrip("/") + path


def won(v) -> str:
    try:
        return f"{int(v):,}원"
    except (TypeError, ValueError):
        return "-"


def kst(dt, fmt="%Y.%m.%d") -> str:
    if not dt:
        return "-"
    return licensing.aware(dt).astimezone(KST).strftime(fmt)


STATE_LABEL = {
    "pending": ("승인 대기", "amber"), "active": ("이용 중", "green"), "grace": ("유예 중", "amber"),
    "expired": ("만료", "red"), "suspended": ("정지", "red"), "cancelled": ("해지", "gray"),
}


def state_badge(lic) -> tuple:
    return STATE_LABEL.get(licensing.state(lic), ("-", "gray"))


templates.env.globals.update(url=url, settings=settings)
templates.env.filters.update(won=won, kst=kst)
templates.env.globals.update(state_badge=state_badge, lic_state=licensing.state, days_left=licensing.days_left,
                             usable=licensing.usable)


def flash(request: Request, message: str, kind: str = "ok"):
    request.session.setdefault("_flash", []).append({"m": message, "k": kind})


def pop_flash(request: Request) -> list:
    return request.session.pop("_flash", [])


templates.env.globals.update(pop_flash=pop_flash)


async def current_account(request: Request, db: AsyncSession) -> Optional[Account]:
    aid = request.session.get("aid")
    if not aid:
        return None
    acc = await db.get(Account, aid)
    if not acc or acc.blocked:
        request.session.clear()
        return None
    return acc


class LoginRequired(HTTPException):
    def __init__(self, next_path: str = ""):
        super().__init__(status_code=303, headers={"Location": url("/login") + (f"?next={next_path}" if next_path else "")})


async def require_account(request: Request, db: AsyncSession) -> Account:
    acc = await current_account(request, db)
    if not acc:
        raise LoginRequired(request.url.path)
    return acc


async def require_operator(request: Request, db: AsyncSession) -> Account:
    acc = await require_account(request, db)
    if not acc.is_operator:
        raise HTTPException(status_code=403, detail="운영자만 접근할 수 있습니다")
    return acc


def render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request=request, name=name, context=ctx)
