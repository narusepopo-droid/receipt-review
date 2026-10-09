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


def progress(lic) -> int:
    """남은 기간 막대 (%)"""
    if not lic.expires_at or not lic.starts_at:
        return 100
    from app.models import now_utc
    total = (licensing.aware(lic.expires_at) - licensing.aware(lic.starts_at)).total_seconds()
    left = (licensing.aware(lic.expires_at) - now_utc()).total_seconds()
    return max(0, min(100, round(left / total * 100))) if total > 0 else 0


def phone_fmt(p: str) -> str:
    p = p or ""
    if len(p) == 11:
        return f"{p[:3]}-{p[3:7]}-{p[7:]}"
    if len(p) == 10:
        return f"{p[:3]}-{p[3:6]}-{p[6:]}"
    return p or "-"


templates.env.globals.update(url=url, settings=settings, progress=progress)
templates.env.filters.update(phone=phone_fmt)
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
