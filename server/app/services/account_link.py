"""
통합 계정 서버 연동

- 로그인: 에이전트·점주웹 로그인을 계정 서버(Firebase 계정 + 이용권 + PC 1대)로 확인
- 계정 서버가 꺼져 있거나 설정이 없으면 None 을 돌려주고, 호출한 쪽은 예전 방식으로 처리 (매장 운영이 멈추지 않게)
- 이용권 상태: 계정 서버가 답함 (연결 안 된 매장은 계정 서버 설정 '유료 모드'에 따라). 오류 시 마지막 답 유지
"""
import logging
import time
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.store import Store, StoreSettings, StoreStatus

logger = logging.getLogger(__name__)
_cache: dict = {}
CACHE_SEC = 120


def enabled() -> bool:
    return bool(settings.ACCOUNT_API_URL and settings.INTERNAL_SECRET)


async def _post(path: str, body: dict, internal: bool = False) -> Optional[httpx.Response]:
    if not enabled():
        return None
    headers = {"X-Internal-Secret": settings.INTERNAL_SECRET} if internal else {}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            return await c.post(settings.ACCOUNT_API_URL.rstrip("/") + path, json=body, headers=headers)
    except Exception as e:
        logger.warning("account server unreachable: %s", e)
        return None


async def account_login(email: str, password: str, device_id: str, device_name: str,
                        store_id: Optional[int]) -> Optional[dict]:
    """계정 서버 이용권 로그인. 연결 실패 시 None"""
    body = {"email": email, "password": password, "product": "receipt_review",
            "device_id": device_id, "device_name": device_name}
    if store_id:
        body["store_id"] = store_id
    r = await _post("/api/v1/license/login", body)
    if r is None or r.status_code >= 500:
        return None
    try:
        return r.json()
    except Exception:
        return None


class LinkError(Exception):
    pass


async def ensure_review_store(db: AsyncSession, acct_store: dict, owner_email: str) -> Store:
    """계정 서버 매장 → 영수증리뷰 매장 (없으면 만들고 서로 연결)"""
    if acct_store.get("review_store_id"):
        store = await db.get(Store, acct_store["review_store_id"])
        if store:
            return store
    from app.routers.ops import _new_store_code
    store = Store(name=acct_store["name"], store_code=await _new_store_code(db), status=StoreStatus.ACTIVE,
                  admin_login_id=None)
    db.add(store)
    await db.flush()
    db.add(StoreSettings(store_id=store.id))
    await db.flush()
    r = await _post("/internal/link-store", {"store_id": acct_store["id"], "review_store_id": store.id,
                                             "review_store_code": store.store_code}, internal=True)
    if r is None or r.status_code != 200:
        # 연결이 안 되면 만들지 않음 (연결 안 된 매장이 생겨 이용권 확인을 빠져나가지 않게) → 다음 로그인 때 다시
        await db.rollback()
        raise LinkError("매장 연결 중 오류가 났습니다. 잠시 후 다시 로그인해 주세요.")
    await db.commit()
    logger.info("created review store %s for account store %s (%s)", store.id, acct_store["id"], owner_email)
    return store


async def license_usable(store_id: int) -> bool:
    """매장 이용권 사용 가능 여부 (2분 캐시).
    계정 서버에 못 물어보면 마지막으로 받은 답을 그대로 씀 (꺼진 동안 만료 매장이 풀리지 않게),
    한 번도 받은 적 없으면 사용 가능 (서버 문제로 멀쩡한 매장이 멈추지 않게)"""
    if not enabled():
        return True
    hit = _cache.get(store_id)
    if hit and hit[0] > time.time():
        return hit[1]
    r = await _post("/internal/review-store", {"review_store_id": store_id}, internal=True)
    ok = None
    if r is not None and r.status_code == 200:
        try:
            ok = bool(r.json().get("usable", True))
        except Exception:
            ok = None
    if ok is None:
        ok = hit[1] if hit else True
        _cache[store_id] = (time.time() + 60, ok)
        return ok
    _cache[store_id] = (time.time() + CACHE_SEC, ok)
    return ok


def clear_cache():
    _cache.clear()


async def owner_login(email: str, password: str) -> Optional[dict]:
    """점주웹 로그인 확인 (PC 등록 없음). 연결 실패 시 None"""
    r = await _post("/internal/owner-login", {"email": email, "password": password}, internal=True)
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:
        return None
