"""영수증 폐기 스케줄러 - 만료된 영수증 자동 삭제"""
import os
import logging
from datetime import datetime, timedelta, timezone, time as dt_time
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Receipt, Store, StoreSettings
from app.models.receipt import ReceiptStatus

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def parse_cutoff_time(cutoff_str: str) -> dt_time:
    try:
        hour, minute = cutoff_str.split(":")
        return dt_time(int(hour), int(minute))
    except:
        return dt_time(5, 0)


def get_business_day_start(
    now: datetime,
    cutoff: dt_time = dt_time(5, 0)
) -> datetime:
    # 영업일 마감 시각(예: 새벽 5시)은 한국 시간 기준
    if now.tzinfo is not None:
        now = now.astimezone(KST)
    cutoff_today = now.replace(
        hour=cutoff.hour,
        minute=cutoff.minute,
        second=0,
        microsecond=0
    )

    if now < cutoff_today:
        return cutoff_today - timedelta(days=1)
    return cutoff_today


def get_business_day_end(
    now: datetime,
    cutoff: dt_time = dt_time(5, 0)
) -> datetime:
    if now.tzinfo is not None:
        now = now.astimezone(KST)
    cutoff_today = now.replace(
        hour=cutoff.hour,
        minute=cutoff.minute,
        second=0,
        microsecond=0
    )

    if now < cutoff_today:
        return cutoff_today
    return cutoff_today + timedelta(days=1)


async def dispose_expired_receipts(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    stats = {
        "assigned_expired": 0,
        "unassigned_expired": 0,
        "files_deleted": 0,
        "errors": [],
    }

    assigned_cutoff = now - timedelta(hours=24)
    stmt = select(Receipt).where(
        Receipt.status == ReceiptStatus.ASSIGNED,
        Receipt.assigned_at < assigned_cutoff
    )
    result = await db.execute(stmt)
    assigned_expired = result.scalars().all()

    for receipt in assigned_expired:
        try:
            await _dispose_receipt(receipt, "assigned_24h_expired", stats)
            stats["assigned_expired"] += 1
        except Exception as e:
            stats["errors"].append(f"Receipt {receipt.id}: {e}")

    stores_stmt = select(Store.id, StoreSettings).join(
        StoreSettings,
        Store.id == StoreSettings.store_id,
        isouter=True
    )
    stores_result = await db.execute(stores_stmt)

    for store_id, settings in stores_result.fetchall():
        cutoff_str = settings.business_day_cutoff if settings else "05:00"
        retention = settings.retention if settings else "end_of_day"

        cutoff = parse_cutoff_time(cutoff_str)

        if retention == "end_of_day":
            expiry_time = get_business_day_start(now, cutoff)
        elif retention.startswith("hours:"):
            try:
                hours = int(retention.split(":")[1])
                expiry_time = now - timedelta(hours=hours)
            except:
                expiry_time = get_business_day_start(now, cutoff)
        else:
            expiry_time = get_business_day_start(now, cutoff)

        stmt = select(Receipt).where(
            Receipt.store_id == store_id,
            Receipt.status == ReceiptStatus.AVAILABLE,
            Receipt.created_at < expiry_time
        )
        result = await db.execute(stmt)
        unassigned_expired = result.scalars().all()

        for receipt in unassigned_expired:
            try:
                await _dispose_receipt(receipt, "retention_expired", stats)
                stats["unassigned_expired"] += 1
            except Exception as e:
                stats["errors"].append(f"Receipt {receipt.id}: {e}")

    # 안전장치 1: 설정과 관계없이 생성 후 24시간이 지난 영수증은 모두 폐기 (D5)
    hard_cutoff = now - timedelta(hours=24)
    stmt = select(Receipt).where(
        Receipt.status != ReceiptStatus.DISPOSED,
        Receipt.created_at < hard_cutoff
    )
    for receipt in (await db.execute(stmt)).scalars().all():
        try:
            await _dispose_receipt(receipt, "created_24h_expired", stats)
            stats["unassigned_expired"] += 1
        except Exception as e:
            stats["errors"].append(f"Receipt {receipt.id}: {e}")

    # 안전장치 2: 폐기 처리됐는데 파일이 남아 있는 경우 파일 삭제
    stmt = select(Receipt).where(
        Receipt.status == ReceiptStatus.DISPOSED,
        (Receipt.image_path.isnot(None)) | (Receipt.raw_bytes_path.isnot(None))
    )
    for receipt in (await db.execute(stmt)).scalars().all():
        reason = receipt.dispose_reason or "disposed"
        await _dispose_receipt(receipt, reason, stats)

    await db.commit()

    logger.info(
        f"Disposal complete: assigned={stats['assigned_expired']}, "
        f"unassigned={stats['unassigned_expired']}, "
        f"files_deleted={stats['files_deleted']}, "
        f"errors={len(stats['errors'])}"
    )

    return stats


async def _dispose_receipt(
    receipt: Receipt,
    reason: str,
    stats: dict
):
    if receipt.raw_bytes_path and os.path.exists(receipt.raw_bytes_path):
        try:
            os.remove(receipt.raw_bytes_path)
            stats["files_deleted"] += 1
        except Exception as e:
            logger.warning(f"Failed to delete raw file {receipt.raw_bytes_path}: {e}")

    if receipt.image_path and os.path.exists(receipt.image_path):
        try:
            os.remove(receipt.image_path)
            stats["files_deleted"] += 1
        except Exception as e:
            logger.warning(f"Failed to delete image file {receipt.image_path}: {e}")

    receipt.status = ReceiptStatus.DISPOSED
    receipt.disposed_at = datetime.now(timezone.utc)
    receipt.dispose_reason = reason
    receipt.raw_bytes_path = None
    receipt.image_path = None
    receipt.raw_text = None


async def dispose_by_approval_no(
    db: AsyncSession,
    store_id: int,
    approval_no: str,
    reason: str = "cancelled"
) -> int:
    stmt = select(Receipt).where(
        Receipt.store_id == store_id,
        Receipt.approval_no == approval_no,
        Receipt.status != ReceiptStatus.DISPOSED
    )
    result = await db.execute(stmt)
    receipts = result.scalars().all()

    stats = {"files_deleted": 0}
    count = 0

    for receipt in receipts:
        await _dispose_receipt(receipt, reason, stats)
        count += 1

    await db.commit()
    return count
