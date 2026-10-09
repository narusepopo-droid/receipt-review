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
