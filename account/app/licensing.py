"""
이용권 규칙

- 연장: 남은 기간이 있으면 기존 만료일 뒤에 이어 붙이고, 만료됐으면 오늘부터. 영구/무료 무제한은 만료일 없음.
- 유예: 만료일 다음 날 23:59(한국 시간)까지 사용 가능. 그 뒤 정지.
- 알림: 만료 7일·3일·1일 전 문자 (같은 만료일에 한 번씩).
- PC: 이용권당 1대. 다른 PC에서 로그인하면 거부. 점주는 30일에 1번 직접 PC 변경 가능, 운영자는 언제든.
- 모든 변경은 LicenseLog 에 기록.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (Account, License, LicenseLog, LicenseStatus, NotificationLog, Plan, PlanKind, Product,
                        Store, Unit, now_utc)

KST = timezone(timedelta(hours=9))
NOTIFY_DAYS = (7, 3, 1)
OWNER_DEVICE_RESET_DAYS = 30


class LicenseError(Exception):
    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


def aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def grace_end(expires_at: datetime) -> datetime:
    """유예 끝: 만료일 다음 날 23:59:59 (한국 시간)"""
    exp_kst = aware(expires_at).astimezone(KST)
    end = (exp_kst + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
    return end.astimezone(timezone.utc)


def state(lic: License, now: Optional[datetime] = None) -> str:
    """pending / active / grace / expired / suspended / cancelled"""
    now = now or now_utc()
    if lic.status == LicenseStatus.CANCELLED:
        return "cancelled"
    if lic.status == LicenseStatus.PENDING:
        return "pending"
    if lic.status == LicenseStatus.SUSPENDED and lic.note != "auto-expired":
        return "suspended"                       # 운영자 정지
    if lic.expires_at is None:
        return "active"
    exp = aware(lic.expires_at)
    if now <= exp:
        return "active"
    if now <= grace_end(exp):
        return "grace"
    return "expired"


def usable(lic: License, now: Optional[datetime] = None) -> bool:
    return state(lic, now) in ("active", "grace")


def days_left(lic: License, now: Optional[datetime] = None) -> Optional[int]:
    if lic.expires_at is None:
        return None
    now = now or now_utc()
    return (aware(lic.expires_at).astimezone(KST).date() - now.astimezone(KST).date()).days


async def log(db: AsyncSession, lic: License, actor: str, action: str, **detail):
    db.add(LicenseLog(license_id=lic.id, actor=actor, action=action, detail=detail))


def _snap(lic: License) -> dict:
    return {"status": lic.status.value if lic.status else None,
            "plan_id": lic.plan_id,
            "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
            "autopay": lic.autopay}


async def get_or_create(db: AsyncSession, account: Account, product: Product, store: Optional[Store]) -> License:
    if product.unit == Unit.STORE and store is None:
        raise LicenseError("매장을 선택해 주세요", "store_required")
    q = select(License).where(License.account_id == account.id, License.product_id == product.id)
    q = q.where(License.store_id == (store.id if store else None)) if store else q.where(License.store_id.is_(None))
    lic = (await db.execute(q)).scalar_one_or_none()
    if lic:
        return lic
    lic = License(account_id=account.id, product_id=product.id, store_id=store.id if store else None,
                  status=LicenseStatus.PENDING)
    db.add(lic)
    await db.flush()
    await log(db, lic, "system", "created")
    return lic


def _add_months(base: datetime, months: int) -> datetime:
    return base + relativedelta(months=months)


async def apply_plan(db: AsyncSession, lic: License, plan: Plan, actor: str, *, months: Optional[int] = None,
                     now: Optional[datetime] = None) -> License:
    """
    요금제 적용 (결제 완료·운영자 지급).
    - 무료(개월 없음)·영구: 만료일 없음 (무제한)
    - 일시불/무료 N개월: 남은 기간 뒤에 N개월 이어 붙임
    - 월 자동결제: 1개월 연장 + 다음 청구일, 약정 종료일 설정
    """
    now = now or now_utc()
    before = _snap(lic)
    base = now
    if lic.expires_at is not None and aware(lic.expires_at) > now and state(lic, now) in ("active", "grace"):
        base = aware(lic.expires_at)

    if plan.kind == PlanKind.LIFETIME or (plan.kind == PlanKind.FREE and not (months or plan.months)):
        lic.expires_at = None
        lic.autopay = False
        lic.next_charge_at = None
    elif plan.kind == PlanKind.MONTHLY:
        lic.expires_at = _add_months(base, 1)
        lic.autopay = True
        lic.autopay_cancel_requested = False
        lic.next_charge_at = lic.expires_at
        if not lic.commitment_ends_at or aware(lic.commitment_ends_at) < now:
            lic.commitment_ends_at = _add_months(now, plan.months or 1)
    else:  # PREPAID or FREE N개월
        if lic.expires_at is None and lic.status == LicenseStatus.ACTIVE and lic.plan and \
                lic.plan.kind in (PlanKind.LIFETIME, PlanKind.FREE):
            pass  # 이미 무제한이면 그대로 (기간권을 사도 줄어들지 않음)
        else:
            lic.expires_at = _add_months(base, months or plan.months or 1)
        lic.autopay = False
        lic.next_charge_at = None

    lic.plan_id = plan.id
    lic.plan = plan
    lic.status = LicenseStatus.ACTIVE
    lic.note = ""
    if not lic.starts_at:
        lic.starts_at = now
    await log(db, lic, actor, "plan_applied", plan=plan.name, before=before, after=_snap(lic))
    return lic


async def set_expiry(db: AsyncSession, lic: License, expires_at: Optional[datetime], actor: str, reason: str = ""):
    before = _snap(lic)
    lic.expires_at = expires_at
    if lic.status in (LicenseStatus.PENDING, LicenseStatus.SUSPENDED) and lic.note == "auto-expired":
        lic.status = LicenseStatus.ACTIVE
        lic.note = ""
    await log(db, lic, actor, "expiry_changed", reason=reason, before=before, after=_snap(lic))


async def set_status(db: AsyncSession, lic: License, status: LicenseStatus, actor: str, reason: str = ""):
    before = _snap(lic)
    lic.status = status
    if status == LicenseStatus.ACTIVE and lic.note == "auto-expired":
        lic.note = ""
    if status == LicenseStatus.ACTIVE and not lic.starts_at:
        lic.starts_at = now_utc()
    await log(db, lic, actor, "status_changed", reason=reason, before=before, after=_snap(lic))


# ───────────── PC 1대 ─────────────

async def bind_device(db: AsyncSession, lic: License, device_id: str, device_name: str = "") -> None:
    device_id = (device_id or "").strip()
    if not device_id:
        raise LicenseError("PC 정보를 확인할 수 없습니다", "no_device")
    if not lic.device_id:
        lic.device_id = device_id
        lic.device_name = device_name[:100]
        lic.device_bound_at = now_utc()
        await log(db, lic, "system", "device_bound", device=device_name)
        return
    if lic.device_id != device_id:
        raise LicenseError(
            f"이 이용권은 다른 PC({lic.device_name or '등록된 PC'})에서 사용 중입니다. "
            "PC를 바꾸셨다면 마이페이지에서 'PC 변경'을 눌러주세요.", "device_mismatch")


async def reset_device(db: AsyncSession, lic: License, actor: str, by_owner: bool) -> None:
    if by_owner and lic.device_reset_at and now_utc() - aware(lic.device_reset_at) < timedelta(days=OWNER_DEVICE_RESET_DAYS):
        nxt = (aware(lic.device_reset_at) + timedelta(days=OWNER_DEVICE_RESET_DAYS)).astimezone(KST)
        raise LicenseError(f"PC 변경은 30일에 한 번 가능합니다 ({nxt:%m월 %d일}부터). 급하시면 고객센터로 연락주세요.",
                           "reset_limited")
    old = lic.device_name
    lic.device_id = None
    lic.device_name = ""
    lic.device_bound_at = None
    lic.device_reset_at = now_utc()
    await log(db, lic, actor, "device_reset", old=old)


# ───────────── 만료 처리·알림 (스케줄러) ─────────────

async def run_expiry_jobs(db: AsyncSession, send_sms, now: Optional[datetime] = None) -> dict:
    """유예 지난 이용권 정지 + 7·3·1일 전 알림"""
    now = now or now_utc()
    stats = {"suspended": 0, "notified": 0}
    rows = (await db.execute(select(License).where(
        License.status == LicenseStatus.ACTIVE, License.expires_at.isnot(None)))).scalars().all()
    for lic in rows:
        st = state(lic, now)
        if st == "expired":
            if lic.autopay and not lic.autopay_cancel_requested:
                continue   # 자동결제 매장은 청구 작업이 처리 (실패 시 그쪽에서 정지)
            lic.status = LicenseStatus.SUSPENDED
            lic.note = "auto-expired"
            await log(db, lic, "system", "expired_suspended")
            stats["suspended"] += 1
            continue
        if lic.autopay and not lic.autopay_cancel_requested:
            continue       # 자동결제는 만료 알림 대신 청구 알림
        dl = days_left(lic, now)
        if dl in NOTIFY_DAYS:
            ref = aware(lic.expires_at).astimezone(KST).strftime("%Y-%m-%d")
            exists = (await db.execute(select(NotificationLog).where(
                NotificationLog.license_id == lic.id, NotificationLog.kind == f"d{dl}",
                NotificationLog.ref == ref))).scalar_one_or_none()
            if exists:
                continue
            account = await db.get(Account, lic.account_id)
            product = await db.get(Product, lic.product_id)
            store = await db.get(Store, lic.store_id) if lic.store_id else None
            target = f"{product.name}" + (f" ({store.name})" if store else "")
            msg = (f"[광고토대왕] {target} 이용 기간이 {dl}일 후({ref}) 끝납니다. "
                   f"연장하시려면 마이페이지에서 결제해 주세요. (만료 다음 날까지 이용 가능)")
            ok = await send_sms(account.phone, msg) if account and account.phone else False
            db.add(NotificationLog(license_id=lic.id, kind=f"d{dl}", ref=ref, message=msg, sent=bool(ok)))
            stats["notified"] += 1
    await db.commit()
    return stats
