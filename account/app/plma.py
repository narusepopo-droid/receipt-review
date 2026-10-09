"""
기존 플마 회원 이용기간 가져오기
플마 회원이 계정 서버에 로그인하면 플마 Firestore 의 본인 정보(active, expires_at, device_id)를 읽어
플마 이용권을 만들어 줌. 계정 서버에서 운영자·결제로 바꾼 적이 없는 이용권(note=plma-import)만 매번 다시 맞춤.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import firebase, licensing
from app.models import Account, License, LicenseStatus, Plan, PlanKind, Product, now_utc

logger = logging.getLogger("plma")
IMPORT_NOTE = "plma-import"


def _exp(s: str):
    try:
        d = datetime.strptime(s.strip(), "%Y-%m-%d")
    except (ValueError, AttributeError):
        return None
    return d.replace(hour=23, minute=59, second=59, tzinfo=licensing.KST).astimezone(timezone.utc)


async def import_plma(db: AsyncSession, acc: Account, uid: str, id_token: str) -> bool:
    try:
        doc = await firebase.get_own_user_doc(uid, id_token)
    except Exception as e:
        logger.warning("plma doc read failed: %s", e)
        return False
    if not doc:
        return False
    product = (await db.execute(select(Product).where(Product.code == "plma"))).scalar_one_or_none()
    if not product:
        return False
    lic = (await db.execute(select(License).where(License.account_id == acc.id, License.product_id == product.id,
                                                  License.store_id.is_(None)))).scalar_one_or_none()
    if lic and lic.note != IMPORT_NOTE and lic.status != LicenseStatus.PENDING:
        return False     # 계정 서버에서 이미 관리 중
    if not lic:
        lic = await licensing.get_or_create(db, acc, product, None)
    free = (await db.execute(select(Plan).where(Plan.product_id == product.id,
                                                Plan.kind == PlanKind.FREE))).scalars().first()
    exp = _exp(doc["expires_at"]) if doc["expires_at"] else None
    expired = exp is not None and exp < now_utc()
    before = licensing._snap(lic)
    lic.plan_id = free.id if free else None
    lic.expires_at = exp
    # 플마는 기간이 끝나면 active=False 로 바꿈 → 기간 만료는 '만료', 그 외 False 는 '정지'
    lic.status = LicenseStatus.ACTIVE if (doc["active"] or expired) else LicenseStatus.SUSPENDED
    lic.starts_at = lic.starts_at or now_utc()
    if doc["device_id"] and not lic.device_id:
        lic.device_id = doc["device_id"]
        lic.device_name = "플마에 등록된 PC"
        lic.device_bound_at = now_utc()
    lic.note = IMPORT_NOTE
    if not acc.name and doc["name"]:
        acc.name = doc["name"]
    after = licensing._snap(lic)
    if before != after:
        await licensing.log(db, lic, "system:plma", "plma_imported", before=before, after=after)
    return True
