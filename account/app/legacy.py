"""
예전 영수증리뷰 점주 계정 자동 이전
Firebase 로그인 실패 → 영수증리뷰 서버에 예전 이메일·비밀번호 확인 →
맞으면 같은 비밀번호로 Firebase 계정 생성, 매장 연결, 무료(무제한) 이용권 지급
"""
import logging
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import firebase, licensing
from app.config import settings
from app.models import Account, Plan, PlanKind, Product, Store

logger = logging.getLogger("legacy")


async def review_internal(path: str, payload: dict) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(settings.REVIEW_API_URL.rstrip("/") + path, json=payload,
                             headers={"X-Internal-Secret": settings.INTERNAL_SECRET})
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.warning("review internal call failed: %s", e)
        return None


async def try_migrate_review_owner(db: AsyncSession, email: str, password: str) -> Optional[Account]:
    data = await review_internal("/internal/legacy-login", {"email": email, "password": password})
    if not data or not data.get("ok"):
        return None
    try:
        res = await firebase.sign_up(email, password)
    except firebase.FirebaseError as e:
        logger.warning("legacy migrate signup failed for %s: %s", email, e.code)
        return None
    from app.routers.auth import upsert_account
    acc = await upsert_account(db, res["localId"], email, name=data.get("owner_name") or data.get("store_name", ""),
                               phone=data.get("phone", ""), biz_no=data.get("biz_no", ""))
    product = (await db.execute(select(Product).where(Product.code == "receipt_review"))).scalar_one()
    for st in data.get("stores", []):
        store = (await db.execute(select(Store).where(Store.review_store_id == st["id"]))).scalar_one_or_none()
        if not store:
            store = Store(account_id=acc.id, name=st["name"], biz_no=st.get("biz_no", ""),
                          review_store_id=st["id"], review_store_code=st.get("store_code"))
            db.add(store)
            await db.flush()
        lic = await licensing.get_or_create(db, acc, product, store)
        if licensing.state(lic) == "pending":
            free = (await db.execute(select(Plan).where(Plan.product_id == product.id,
                                                        Plan.kind == PlanKind.FREE))).scalars().first()
            await licensing.apply_plan(db, lic, free, "system:legacy-migration")
    await db.commit()
    return acc
