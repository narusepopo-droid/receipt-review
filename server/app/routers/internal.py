"""서버끼리 쓰는 API (계정 서버 ↔ 영수증리뷰). 공유 비밀 헤더 필수, 외부에는 nginx 로 막음"""
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.store import Store
from app.security import verify_password

router = APIRouter(prefix="/internal", tags=["internal"])


def _check(secret: str):
    if not settings.INTERNAL_SECRET or not secret or not hmac.compare_digest(secret, settings.INTERNAL_SECRET):
        raise HTTPException(status_code=403)


class LegacyLogin(BaseModel):
    email: str
    password: str


@router.post("/legacy-login")
async def legacy_login(req: LegacyLogin, x_internal_secret: str = Header(""), db: AsyncSession = Depends(get_db)):
    """예전 점주 계정(매장 아이디·비밀번호) 확인 → 계정 서버가 자동 이전에 사용"""
    _check(x_internal_secret)
    store = (await db.execute(select(Store).where(Store.admin_login_id == req.email.strip()))).scalar_one_or_none()
    if not store or not verify_password(req.password, store.admin_password_hash or ""):
        return {"ok": False}
    return {"ok": True, "store_name": store.name, "biz_no": store.biz_no or "",
            "stores": [{"id": store.id, "name": store.name, "biz_no": store.biz_no or "",
                        "store_code": store.store_code}]}


@router.get("/ops-summary")
async def ops_summary(x_internal_secret: str = Header(""), db: AsyncSession = Depends(get_db)):
    """마스터 관리자 페이지용 영수증리뷰 현황 숫자"""
    _check(x_internal_secret)
    from sqlalchemy import func
    from app.models.receipt import Receipt, ReceiptClassification, ReceiptStatus
    from app.models.session import ReviewSession
    from app.models.store import StoreStatus
    from app.routers.ops import _kst_day_start, _latest_agents, agent_health
    stores = (await db.execute(select(Store))).scalars().all()
    agents = await _latest_agents(db)
    active = [s for s in stores if s.status == StoreStatus.ACTIVE]
    offline = [s.name for s in active if agent_health(agents.get(s.id))[0] == "offline"]
    today = _kst_day_start()
    return {
        "stores": len(stores), "active_stores": len(active), "offline_stores": offline,
        "today_sessions": (await db.execute(select(func.count(ReviewSession.id)).where(
            ReviewSession.started_at >= today))).scalar() or 0,
        "today_completed": (await db.execute(select(func.count(ReviewSession.id)).where(
            ReviewSession.started_at >= today, ReviewSession.completed_at.isnot(None)))).scalar() or 0,
        "unclassified": (await db.execute(select(func.count(Receipt.id)).where(
            Receipt.classification == ReceiptClassification.UNCLASSIFIED,
            Receipt.status != ReceiptStatus.DISPOSED))).scalar() or 0,
    }


@router.get("/ops-stores")
async def ops_stores(x_internal_secret: str = Header(""), db: AsyncSession = Depends(get_db)):
    """마스터 '전체 회원' 화면용 매장 목록 (예전 매장 계정 포함)"""
    _check(x_internal_secret)
    from app.models.store import StoreStatus
    from app.routers.ops import _latest_agents, agent_health
    agents = await _latest_agents(db)
    out = []
    for s in (await db.execute(select(Store).order_by(Store.id))).scalars():
        out.append({"id": s.id, "name": s.name, "store_code": s.store_code, "login": s.admin_login_id or "",
                    "active": s.status == StoreStatus.ACTIVE, "pos": agent_health(agents.get(s.id))[0],
                    "created_at": s.created_at.isoformat() if s.created_at else ""})
    return {"stores": out}
