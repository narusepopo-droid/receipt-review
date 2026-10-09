"""
주문: 견적 → 주문 생성 → (결제) → 이용권 적용
월 자동결제 청구 작업 포함
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import licensing, payments
from app.models import (Account, BillingKey, License, LicenseStatus, Order, OrderItem, OrderStatus, Plan, PlanKind,
                        Product, Promotion, Setting, Store, now_utc)
from app.pricing import DEFAULT_MAX_DISCOUNT_PCT, Line, build_quote, plan_price

logger = logging.getLogger("orders")


async def get_setting(db: AsyncSession, key: str, default):
    row = await db.get(Setting, key)
    return row.value.get("v", default) if row else default


async def put_setting(db: AsyncSession, key: str, value):
    row = await db.get(Setting, key)
    if row:
        row.value = {"v": value}
    else:
        db.add(Setting(key=key, value={"v": value}))


async def quote(db: AsyncSession, lines: list[Line], promo_code: Optional[str] = None):
    promos = (await db.execute(select(Promotion).where(Promotion.active.is_(True)))).scalars().all()
    max_pct = await get_setting(db, "max_discount_pct", DEFAULT_MAX_DISCOUNT_PCT)
    return build_quote(lines, list(promos), promo_code, max_pct)


async def create_order(db: AsyncSession, account: Account, lines: list[Line], promo_code: Optional[str] = None,
                       method: str = "card") -> tuple[Order, object]:
    q = await quote(db, lines, promo_code)
    if q.promo_code and q.promo_error:
        raise ValueError(q.promo_error)
    names = [f"{l.product.name} {l.plan.name}" for l in lines]
    title = names[0] + (f" 외 {len(names) - 1}건" if len(names) > 1 else "")
    order = Order(account_id=account.id, title=title[:200], list_amount=q.list_amount, discounts=q.discounts,
                  amount=q.amount, promo_code=q.promo_code, method=method, status=OrderStatus.PENDING)
    db.add(order)
    await db.flush()
    for l in lines:
        store = await db.get(Store, l.store_id) if l.store_id else None
        lic = await licensing.get_or_create(db, account, l.product, store)
        db.add(OrderItem(order_id=order.id, product_id=l.product.id, plan_id=l.plan.id, store_id=l.store_id,
                         license_id=lic.id, list_amount=l.list_amount, amount=l.amount))
    order.discounts = q.discounts + [{"label": "_promotion_ids", "amount": 0, "ids": q.promotion_ids}]
    await db.flush()
    return order, q


async def fulfill(db: AsyncSession, order: Order, actor: str, payment_key: str = None, receipt_url: str = None):
    """결제 완료 → 이용권 적용 (중복 호출 안전)"""
    if order.status == OrderStatus.PAID:
        return order
    items = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    for it in items:
        lic = await db.get(License, it.license_id)
        plan = await db.get(Plan, it.plan_id)
        await licensing.apply_plan(db, lic, plan, f"{actor}:{order.id}")
    ids = next((d.get("ids", []) for d in (order.discounts or []) if d.get("label") == "_promotion_ids"), [])
    for pid in ids:
        promo = await db.get(Promotion, pid)
        if promo:
            promo.used_count += 1
    order.status = OrderStatus.PAID
    order.paid_at = now_utc()
    order.toss_payment_key = payment_key or order.toss_payment_key
    order.receipt_url = receipt_url or order.receipt_url
    return order


def public_discounts(order: Order) -> list:
    return [d for d in (order.discounts or []) if not d.get("label", "").startswith("_")]


async def active_billing_key(db: AsyncSession, account_id: int) -> Optional[BillingKey]:
    return (await db.execute(select(BillingKey).where(BillingKey.account_id == account_id, BillingKey.active.is_(True))
                             .order_by(BillingKey.id.desc()))).scalars().first()


# ───────────── 월 자동결제 청구 (스케줄러, 하루 여러 번) ─────────────

async def run_autopay(db: AsyncSession, send_sms, now: Optional[datetime] = None) -> dict:
    now = now or now_utc()
    stats = {"charged": 0, "failed": 0, "stopped": 0}
    due = (await db.execute(select(License).where(
        License.autopay.is_(True), License.next_charge_at.isnot(None), License.next_charge_at <= now,
        License.status == LicenseStatus.ACTIVE))).scalars().all()
    for lic in due:
        account = await db.get(Account, lic.account_id)
        product = await db.get(Product, lic.product_id)
        plan = await db.get(Plan, lic.plan_id) if lic.plan_id else None
        # 해지 신청: 약정이 끝났으면 청구 멈춤 (남은 기간까지 이용 후 만료)
        commit_end = licensing.aware(lic.commitment_ends_at)
        if lic.autopay_cancel_requested and (not commit_end or commit_end <= now):
            lic.autopay = False
            lic.next_charge_at = None
            await licensing.log(db, lic, "system", "autopay_stopped")
            stats["stopped"] += 1
            continue
        if not plan or plan.kind != PlanKind.MONTHLY:
            lic.autopay = False
            continue
        amount = plan_price(product, plan)
        bk = await active_billing_key(db, account.id)
        order = Order(account_id=account.id, title=f"{product.name} {plan.name} 월 청구", list_amount=product.monthly_price,
                      discounts=[], amount=amount, method="billing", status=OrderStatus.PENDING)
        db.add(order)
        await db.flush()
        db.add(OrderItem(order_id=order.id, product_id=product.id, plan_id=plan.id, store_id=lic.store_id,
                         license_id=lic.id, list_amount=product.monthly_price, amount=amount))
        try:
            if amount > 0:
                if not bk:
                    raise payments.TossError("등록된 카드가 없습니다")
                res = await payments.charge_billing(payments.decrypt(bk.billing_key_enc), account.toss_customer_key,
                                                    amount, order.id, order.title)
                order.toss_payment_key = res.get("paymentKey")
                order.receipt_url = (res.get("receipt") or {}).get("url")
            order.status = OrderStatus.PAID
            order.paid_at = now
            before = licensing._snap(lic)
            lic.expires_at = licensing._add_months(licensing.aware(lic.expires_at) or now, 1)
            lic.next_charge_at = lic.expires_at
            await licensing.log(db, lic, f"autopay:{order.id}", "charged", amount=amount, before=before,
                                after=licensing._snap(lic))
            stats["charged"] += 1
        except Exception as e:
            order.status = OrderStatus.FAILED
            order.fail_reason = str(e)[:300]
            # 다음 날 다시 시도, 유예(만료 다음 날)까지 실패하면 정지
            if now > licensing.grace_end(lic.expires_at):
                lic.status = LicenseStatus.SUSPENDED
                lic.note = "auto-expired"
                await licensing.log(db, lic, "system", "autopay_failed_suspended", reason=str(e)[:200])
            else:
                lic.next_charge_at = now + timedelta(days=1)
                await licensing.log(db, lic, "system", "autopay_failed_retry", reason=str(e)[:200])
            if account.phone:
                await send_sms(account.phone, f"[광고토대왕] {product.name} 월 이용료 결제에 실패했습니다. "
                                              f"마이페이지에서 카드를 확인해 주세요. ({str(e)[:40]})")
            stats["failed"] += 1
    await db.commit()
    return stats
