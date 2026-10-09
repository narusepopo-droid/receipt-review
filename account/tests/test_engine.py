"""가격·이용권·알림·자동결제 엔진 테스트 (메모리 DB)"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import licensing, orders
from app.models import (Account, Base, License, LicenseStatus, NotificationLog, Order, OrderStatus, Plan, PlanKind,
                        Product, Promotion, Store)
from app.pricing import Line, build_quote, plan_price, plan_rule_warnings
from app.seed import seed

KST = timezone(timedelta(hours=9))


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        await seed(s)
        yield s
    await engine.dispose()


async def _prod(db, code):
    return (await db.execute(select(Product).where(Product.code == code))).scalar_one()


async def _plan(db, product, kind, months=None):
    q = select(Plan).where(Plan.product_id == product.id, Plan.kind == kind)
    if months:
        q = q.where(Plan.months == months)
    return (await db.execute(q)).scalars().first()


async def _account(db, email="a@test.com", phone="01012345678"):
    a = Account(email=email, phone=phone, firebase_uid="uid-" + email)
    db.add(a)
    await db.flush()
    return a


# ───────── 가격 ─────────

@pytest.mark.asyncio
async def test_default_plans_follow_discount_rules(db):
    for code in ("plma", "receipt_review"):
        p = await _prod(db, code)
        plans = (await db.execute(select(Plan).where(Plan.product_id == p.id))).scalars().all()
        assert plan_rule_warnings(p, plans) == [], code


@pytest.mark.asyncio
async def test_prices(db):
    rr = await _prod(db, "receipt_review")          # 월 39,000
    y1 = await _plan(db, rr, PlanKind.PREPAID, 12)  # 15%
    life = await _plan(db, rr, PlanKind.LIFETIME)   # 36개월 × 40%
    assert plan_price(rr, y1) == 397800
    assert plan_price(rr, life) == 842400
    y1.price_override = 350000
    assert plan_price(rr, y1) == 350000


@pytest.mark.asyncio
async def test_bundle_and_coupon_and_cap(db):
    rr, pm = await _prod(db, "receipt_review"), await _prod(db, "plma")
    y_rr, y_pm = await _plan(db, rr, PlanKind.PREPAID, 12), await _plan(db, pm, PlanKind.PREPAID, 12)
    promos = (await db.execute(select(Promotion))).scalars().all()
    # 하나만 사면 묶음 할인 없음
    q1 = build_quote([Line(rr, y_rr)], promos)
    assert q1.amount == 397800 and len(q1.discounts) == 1
    # 둘 다 사면 묶음 10%
    q2 = build_quote([Line(rr, y_rr), Line(pm, y_pm)], promos)
    sub = plan_price(rr, y_rr) + plan_price(pm, y_pm)
    assert q2.amount == sub - round(sub * 0.1 / 100) * 100
    # 쿠폰
    coupon = Promotion(id=99, name="오픈 기념", code="OPEN20", kind="percent", value=20)
    q3 = build_quote([Line(rr, y_rr)], promos + [coupon], "open20")
    assert q3.promo_error == "" and q3.amount < q1.amount
    q4 = build_quote([Line(rr, y_rr)], promos, "NOPE")
    assert q4.promo_error
    # 최대 할인 한도 (정가 대비 30%)
    q5 = build_quote([Line(rr, y_rr)], promos + [coupon], "OPEN20", max_discount_pct=30)
    assert q5.amount == q5.list_amount - round(q5.list_amount * 0.3 / 100) * 100


@pytest.mark.asyncio
async def test_expired_coupon(db):
    rr = await _prod(db, "receipt_review")
    y = await _plan(db, rr, PlanKind.PREPAID, 12)
    old = Promotion(id=5, name="지난 행사", code="OLD", kind="amount", value=10000,
                    ends_at=datetime.now(timezone.utc) - timedelta(days=1))
    q = build_quote([Line(rr, y)], [old], "OLD")
    assert q.promo_error and q.amount == plan_price(rr, y)


# ───────── 이용권 ─────────

@pytest.mark.asyncio
async def test_extend_appends_to_remaining(db):
    rr = await _prod(db, "receipt_review")
    acc = await _account(db)
    store = Store(account_id=acc.id, name="매장")
    db.add(store)
    await db.flush()
    lic = await licensing.get_or_create(db, acc, rr, store)
    assert licensing.state(lic) == "pending"
    y1 = await _plan(db, rr, PlanKind.PREPAID, 12)
    now = datetime(2026, 1, 10, 3, tzinfo=timezone.utc)
    await licensing.apply_plan(db, lic, y1, "test", now=now)
    assert lic.expires_at == datetime(2027, 1, 10, 3, tzinfo=timezone.utc)
    # 남은 기간 있을 때 연장 → 만료일 뒤에 이어붙임
    await licensing.apply_plan(db, lic, y1, "test", now=datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert lic.expires_at == datetime(2028, 1, 10, 3, tzinfo=timezone.utc)
    # 만료 후 연장 → 오늘부터
    later = datetime(2028, 3, 1, tzinfo=timezone.utc)
    await licensing.apply_plan(db, lic, y1, "test", now=later)
    assert lic.expires_at == datetime(2029, 3, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_lifetime_and_free_unlimited(db):
    pm = await _prod(db, "plma")
    acc = await _account(db)
    lic = await licensing.get_or_create(db, acc, pm, None)
    await licensing.apply_plan(db, lic, await _plan(db, pm, PlanKind.FREE), "test")
    assert lic.expires_at is None and licensing.state(lic) == "active"
    # 무제한 상태에서 기간권을 사도 줄어들지 않음
    await licensing.apply_plan(db, lic, await _plan(db, pm, PlanKind.PREPAID, 12), "test")
    assert lic.expires_at is None


@pytest.mark.asyncio
async def test_store_product_requires_store(db):
    rr = await _prod(db, "receipt_review")
    acc = await _account(db)
    with pytest.raises(licensing.LicenseError):
        await licensing.get_or_create(db, acc, rr, None)


@pytest.mark.asyncio
async def test_grace_until_next_day_end(db):
    lic = License(status=LicenseStatus.ACTIVE, expires_at=datetime(2026, 5, 10, 14, 59, tzinfo=timezone.utc))  # 5/10 23:59 KST
    assert licensing.state(lic, datetime(2026, 5, 10, 14, 0, tzinfo=timezone.utc)) == "active"
    assert licensing.state(lic, datetime(2026, 5, 11, 10, 0, tzinfo=timezone.utc)) == "grace"     # 5/11 19시 KST
    assert licensing.state(lic, datetime(2026, 5, 11, 14, 59, tzinfo=timezone.utc)) == "grace"    # 5/11 23:59 KST
    assert licensing.state(lic, datetime(2026, 5, 11, 15, 1, tzinfo=timezone.utc)) == "expired"   # 5/12 00:01 KST


@pytest.mark.asyncio
async def test_device_lock(db):
    pm = await _prod(db, "plma")
    acc = await _account(db)
    lic = await licensing.get_or_create(db, acc, pm, None)
    await licensing.bind_device(db, lic, "PC-A", "카운터 PC")
    await licensing.bind_device(db, lic, "PC-A")
    with pytest.raises(licensing.LicenseError) as e:
        await licensing.bind_device(db, lic, "PC-B")
    assert e.value.code == "device_mismatch"
    await licensing.reset_device(db, lic, "owner", by_owner=True)
    await licensing.bind_device(db, lic, "PC-B")
    with pytest.raises(licensing.LicenseError):              # 30일 안에 또 바꾸기 불가
        await licensing.reset_device(db, lic, "owner", by_owner=True)
    await licensing.reset_device(db, lic, "operator", by_owner=False)   # 운영자는 가능
    assert lic.device_id is None


@pytest.mark.asyncio
async def test_expiry_notifications_and_suspend(db):
    rr = await _prod(db, "receipt_review")
    acc = await _account(db)
    stores = []
    for n in range(3):
        s = Store(account_id=acc.id, name=f"매장{n}")
        db.add(s)
        stores.append(s)
    await db.flush()
    now = datetime(2026, 3, 1, 1, 0, tzinfo=timezone.utc)   # 3/1 10:00 KST
    l7 = await licensing.get_or_create(db, acc, rr, stores[0])
    l7.status, l7.expires_at = LicenseStatus.ACTIVE, datetime(2026, 3, 8, 14, 59, tzinfo=timezone.utc)
    l1 = await licensing.get_or_create(db, acc, rr, stores[1])
    l1.status, l1.expires_at = LicenseStatus.ACTIVE, datetime(2026, 3, 2, 14, 59, tzinfo=timezone.utc)
    lx = await licensing.get_or_create(db, acc, rr, stores[2])
    lx.status, lx.expires_at = LicenseStatus.ACTIVE, datetime(2026, 2, 26, 14, 59, tzinfo=timezone.utc)
    await db.flush()
    sent = []

    async def fake_sms(phone, msg):
        sent.append((phone, msg))
        return True

    stats = await licensing.run_expiry_jobs(db, fake_sms, now=now)
    assert stats == {"suspended": 1, "notified": 2}
    assert any("7일 후" in m for _, m in sent) and any("1일 후" in m for _, m in sent)
    assert lx.status == LicenseStatus.SUSPENDED and licensing.state(lx, now) == "expired"
    # 같은 날 다시 돌려도 중복 발송 없음
    stats2 = await licensing.run_expiry_jobs(db, fake_sms, now=now + timedelta(hours=1))
    assert stats2["notified"] == 0
    # 정지된 이용권도 연장하면 다시 사용 가능
    y1 = await _plan(db, rr, PlanKind.PREPAID, 12)
    await licensing.apply_plan(db, lx, y1, "test", now=now)
    assert licensing.state(lx, now) == "active"


@pytest.mark.asyncio
async def test_order_fulfill_and_free_checkout(db):
    rr = await _prod(db, "receipt_review")
    acc = await _account(db)
    store = Store(account_id=acc.id, name="매장")
    db.add(store)
    await db.flush()
    y2 = await _plan(db, rr, PlanKind.PREPAID, 24)
    coupon = Promotion(name="1천원", code="K1000", kind="amount", value=1000)
    db.add(coupon)
    await db.flush()
    order, q = await orders.create_order(db, acc, [Line(rr, y2, store.id)], "K1000")
    assert order.amount == plan_price(rr, y2) - 1000
    await orders.fulfill(db, order, "test")
    await orders.fulfill(db, order, "test")       # 두 번 불러도 한 번만 적용
    lic = (await db.execute(select(License).where(License.store_id == store.id))).scalar_one()
    assert licensing.state(lic) == "active" and order.status == OrderStatus.PAID
    assert licensing.days_left(lic) > 700
    assert coupon.used_count == 1


@pytest.mark.asyncio
async def test_monthly_autopay(db, monkeypatch):
    rr = await _prod(db, "receipt_review")
    acc = await _account(db)
    store = Store(account_id=acc.id, name="매장")
    db.add(store)
    await db.flush()
    m12 = await _plan(db, rr, PlanKind.MONTHLY, 12)
    lic = await licensing.get_or_create(db, acc, rr, store)
    start = datetime(2026, 1, 15, 3, tzinfo=timezone.utc)
    await licensing.apply_plan(db, lic, m12, "test", now=start)
    assert lic.autopay and lic.expires_at == datetime(2026, 2, 15, 3, tzinfo=timezone.utc)
    assert lic.commitment_ends_at == datetime(2027, 1, 15, 3, tzinfo=timezone.utc)

    from app import payments
    from app.models import BillingKey
    db.add(BillingKey(account_id=acc.id, billing_key_enc=payments.encrypt("bk_test")))
    await db.flush()
    calls = []

    async def fake_charge(bk, ck, amount, oid, name):
        calls.append(amount)
        if len(calls) == 2:
            raise payments.TossError("한도 초과")
        return {"paymentKey": "pk" + oid}

    monkeypatch.setattr(payments, "charge_billing", fake_charge)

    async def sms(p, m):
        return True

    # 1회차 청구 성공 → 한 달 연장
    s = await orders.run_autopay(db, sms, now=datetime(2026, 2, 15, 4, tzinfo=timezone.utc))
    assert s["charged"] == 1 and lic.expires_at == datetime(2026, 3, 15, 3, tzinfo=timezone.utc)
    # 2회차 실패 → 다음 날 재시도
    s = await orders.run_autopay(db, sms, now=datetime(2026, 3, 15, 4, tzinfo=timezone.utc))
    assert s["failed"] == 1 and lic.status == LicenseStatus.ACTIVE
    # 3회차(다음 날) 성공
    s = await orders.run_autopay(db, sms, now=datetime(2026, 3, 16, 4, tzinfo=timezone.utc))
    assert s["charged"] == 1 and lic.expires_at == datetime(2026, 4, 15, 3, tzinfo=timezone.utc)
    # 약정 중 해지 신청 → 약정 끝날 때까지 계속 청구
    lic.autopay_cancel_requested = True
    s = await orders.run_autopay(db, sms, now=datetime(2026, 4, 15, 4, tzinfo=timezone.utc))
    assert s["charged"] == 1
    # 약정 종료 후 → 청구 멈춤
    lic.next_charge_at = datetime(2027, 1, 16, tzinfo=timezone.utc)
    s = await orders.run_autopay(db, sms, now=datetime(2027, 1, 16, 1, tzinfo=timezone.utc))
    assert s["stopped"] == 1 and not lic.autopay
