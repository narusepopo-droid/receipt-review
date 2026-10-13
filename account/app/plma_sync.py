"""
플마 이용권 → 플마 프로그램이 보는 Firestore users/{uid} 반영

이용권 변경 기록(licensing.log)마다 호출. 결제·입금 확인·월 청구·만료 정지·운영자 조정·환불 후 조정 모두 여기로 모임.
- expires_at: 유예 끝 날짜(만료 다음 날, 프로그램은 '오늘 > 날짜' 면 막음), 무제한이면 빈 값
- active: 사용 가능(이용 중·유예)이면 True
- PC: 운영자/점주가 PC 변경을 누르면 프로그램 쪽 PC 기록도 지움 (프로그램이 다음 실행 때 새 PC 등록)
실패해도 결제·관리 작업은 그대로 진행 (로그만 남김)
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, License, Product

logger = logging.getLogger("plma_sync")
SKIP = {"created", "plma_imported", "device_bound"}


async def push(db: AsyncSession, lic: License, action: str) -> None:
    if action in SKIP or not lic.product_id:
        return
    from app import firebase, licensing
    try:
        product = await db.get(Product, lic.product_id)
        if not product or product.code != "plma" or not firebase.sa_available():
            return
        st = licensing.state(lic)
        if st == "pending":
            return
        acc = await db.get(Account, lic.account_id)
        if not acc or not acc.firebase_uid:
            return
        exp = "" if lic.expires_at is None else \
            licensing.grace_end(lic.expires_at).astimezone(licensing.KST).strftime("%Y-%m-%d")
        ok = await firebase.sync_plma_user(acc.firebase_uid, active=st in ("active", "grace"), expires_at=exp,
                                           email=acc.email, name=acc.name,
                                           device_id="" if action == "device_reset" else None)
        if not ok:
            logger.warning("plma sync failed: license %s (%s)", lic.id, action)
    except Exception as e:
        logger.warning("plma sync error: license %s (%s): %s", lic.id, action, e)
