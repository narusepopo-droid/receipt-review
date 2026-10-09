"""운영자 화면"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import licensing, orders, payments
from app.config import settings
from app.db import get_db
from app.models import (Account, License, LicenseLog, LicenseStatus, NotificationLog, Order, OrderItem, OrderStatus,
                        Plan, PlanKind, Product, Promotion, SignupPolicy, Store, Unit, now_utc)
from app.pricing import effective_monthly, list_price, plan_price, plan_rule_warnings
from app.web import KST, flash, render, require_operator, url

router = APIRouter(prefix="/ops")


def _int(v, default=None):
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _date(v):
    """'2026-12-31' → 그날 23:59:59 KST"""
    v = (v or "").strip()
    if not v:
        return None
    d = datetime.strptime(v, "%Y-%m-%d")
    return d.replace(hour=23, minute=59, second=59, tzinfo=KST).astimezone(timezone.utc)


@router.get("")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    op = await require_operator(request, db)
    now = now_utc()
    month_start = now.astimezone(KST).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    products = (await db.execute(select(Product).order_by(Product.sort))).scalars().all()
    lics = (await db.execute(select(License))).scalars().all()
    stats = []
    for p in products:
        pl = [l for l in lics if l.product_id == p.id]
        states = [licensing.state(l, now) for l in pl]
        stats.append({"product": p, "total": len(pl), "active": states.count("active"),
                      "grace": states.count("grace"), "pending": states.count("pending"),
                      "expired": states.count("expired") + states.count("suspended"),
                      "soon": sum(1 for l in pl if licensing.state(l, now) == "active"
                                  and (licensing.days_left(l, now) or 999) <= 7)})
    revenue_month = (await db.execute(select(func.coalesce(func.sum(Order.amount), 0)).where(
        Order.status == OrderStatus.PAID, Order.paid_at >= month_start))).scalar()
    revenue_total = (await db.execute(select(func.coalesce(func.sum(Order.amount), 0)).where(
        Order.status == OrderStatus.PAID))).scalar()
    accounts = (await db.execute(select(func.count(Account.id)))).scalar()
    new_week = (await db.execute(select(func.count(Account.id)).where(
        Account.created_at >= now - timedelta(days=7)))).scalar()
    pending = [l for l in lics if licensing.state(l, now) == "pending"]
    for l in pending:
        await db.refresh(l, ["account", "product", "store"])
    soon = sorted([l for l in lics if licensing.state(l, now) in ("active", "grace") and l.expires_at
                   and (licensing.days_left(l, now) or 999) <= 7], key=lambda l: l.expires_at)[:20]
    for l in soon:
        await db.refresh(l, ["account", "product", "store"])
    recent = (await db.execute(select(Order).order_by(Order.created_at.desc()).limit(8))).scalars().all()
    for o in recent:
        await db.refresh(o, ["account"])
    return render(request, "ops/dashboard.html", op=op, stats=stats, revenue_month=revenue_month,
                  revenue_total=revenue_total, accounts=accounts, new_week=new_week, pending=pending, soon=soon,
                  recent=recent, nav="dash")


# ───────────── 회원 ─────────────

@router.get("/accounts")
async def accounts(request: Request, q: str = "", product: str = "", state: str = "",
                   db: AsyncSession = Depends(get_db)):
    op = await require_operator(request, db)
    stmt = select(Account).order_by(Account.created_at.desc())
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Account.email.ilike(like), Account.name.ilike(like), Account.phone.ilike(like),
                              Account.company.ilike(like),
                              Account.id.in_(select(Store.account_id).where(Store.name.ilike(like)))))
    rows = (await db.execute(stmt.limit(500))).scalars().all()
    products = (await db.execute(select(Product).order_by(Product.sort))).scalars().all()
    data = []
    for a in rows:
        lics = (await db.execute(select(License).where(License.account_id == a.id))).scalars().all()
        for l in lics:
            await db.refresh(l, ["product", "store"])
        if product:
            lics_f = [l for l in lics if l.product.code == product]
            if not lics_f:
                continue
        else:
            lics_f = lics
        if state and not any(licensing.state(l) == state for l in lics_f):
            continue
        data.append({"a": a, "lics": lics})
    return render(request, "ops/accounts.html", op=op, rows=data, q=q, products=products, product=product,
                  state=state, nav="accounts")


@router.get("/accounts/{aid}")
async def account_detail(request: Request, aid: int, db: AsyncSession = Depends(get_db)):
    op = await require_operator(request, db)
    acc = await db.get(Account, aid)
    if not acc:
        raise HTTPException(404)
    lics = (await db.execute(select(License).where(License.account_id == aid).order_by(License.id))).scalars().all()
    for l in lics:
        await db.refresh(l, ["product", "store", "plan"])
    stores = (await db.execute(select(Store).where(Store.account_id == aid).order_by(Store.id))).scalars().all()
    products = (await db.execute(select(Product).order_by(Product.sort))).scalars().all()
    plans = (await db.execute(select(Plan).order_by(Plan.product_id, Plan.sort))).scalars().all()
    order_rows = (await db.execute(select(Order).where(Order.account_id == aid).order_by(Order.created_at.desc())
                                   .limit(50))).scalars().all()
    logs = (await db.execute(select(LicenseLog).where(LicenseLog.license_id.in_([l.id for l in lics] or [0]))
                             .order_by(LicenseLog.created_at.desc()).limit(60))).scalars().all()
    lic_name = {l.id: l.product.name + (f" · {l.store.name}" if l.store else "") for l in lics}
    bk = await orders.active_billing_key(db, aid)
    return render(request, "ops/account.html", op=op, acc=acc, lics=lics, stores=stores, products=products,
                  plans=plans, orders=order_rows, logs=logs, lic_name=lic_name, billing_key=bk,
                  public_discounts=orders.public_discounts, nav="accounts", Unit=Unit)


@router.post("/accounts/{aid}")
async def account_save(request: Request, aid: int, db: AsyncSession = Depends(get_db)):
    op = await require_operator(request, db)
    acc = await db.get(Account, aid)
    if not acc:
        raise HTTPException(404)
    f = await request.form()
    for k in ("name", "phone", "company", "biz_no", "memo"):
        if k in f:
            setattr(acc, k, str(f[k]).strip())
    acc.blocked = bool(f.get("blocked"))
    await db.commit()
    flash(request, "회원 정보를 저장했습니다.")
    return RedirectResponse(url(f"/ops/accounts/{aid}"), status_code=303)


@router.post("/accounts/{aid}/stores")
async def account_add_store(request: Request, aid: int, db: AsyncSession = Depends(get_db)):
    op = await require_operator(request, db)
    acc = await db.get(Account, aid)
    f = await request.form()
    name = str(f.get("name", "")).strip()
    if not acc or not name:
        flash(request, "매장 이름을 입력해 주세요.", "err")
        return RedirectResponse(url(f"/ops/accounts/{aid}"), status_code=303)
    store = Store(account_id=aid, name=name, biz_no=str(f.get("biz_no", "")).strip(),
                  review_store_id=_int(f.get("review_store_id")))
    db.add(store)
    await db.flush()
    for p in (await db.execute(select(Product).where(Product.unit == Unit.STORE))).scalars():
        await licensing.get_or_create(db, acc, p, store)
    await db.commit()
    flash(request, f"매장 '{name}'을 추가했습니다.")
    return RedirectResponse(url(f"/ops/accounts/{aid}"), status_code=303)


@router.post("/accounts/{aid}/licenses")
async def account_add_license(request: Request, aid: int, db: AsyncSession = Depends(get_db)):
    """계정 단위 상품 이용권 추가 (운영자)"""
    await require_operator(request, db)
    acc = await db.get(Account, aid)
    f = await request.form()
    product = await db.get(Product, _int(f.get("product_id")))
    if not acc or not product:
        raise HTTPException(404)
    store = await db.get(Store, _int(f.get("store_id"))) if f.get("store_id") else None
    try:
        await licensing.get_or_create(db, acc, product, store)
        await db.commit()
    except licensing.LicenseError as e:
        flash(request, str(e), "err")
    return RedirectResponse(url(f"/ops/accounts/{aid}"), status_code=303)


@router.post("/licenses/{lid}")
async def license_action(request: Request, lid: int, db: AsyncSession = Depends(get_db)):
    op = await require_operator(request, db)
    lic = await db.get(License, lid)
    if not lic:
        raise HTTPException(404)
    f = await request.form()
    action = f.get("action")
    actor = f"operator:{op.email}"
    account_id = lic.account_id
    reason = str(f.get("reason", "")).strip()
    try:
        prod0 = await db.get(Product, lic.product_id)
        from app import firebase as _fb
        if prod0.code == "plma" and action in ("approve", "grant") and not _fb.sa_available() and lic.note != "plma-import":
            raise licensing.LicenseError("플마 신규 승인은 서비스 계정 키 연결 전까지 플마 관리자 프로그램에서 해주세요 "
                                         "(여기서 승인해도 플마 프로그램이 인식하지 못해요)")
        if action == "approve":                  # 승인 = 무료(무제한) 지급
            plan = (await db.execute(select(Plan).where(Plan.product_id == lic.product_id,
                                                        Plan.kind == PlanKind.FREE))).scalars().first()
            await licensing.apply_plan(db, lic, plan, actor)
            msg = "승인했습니다 (무료·무제한)."
            acc_ = await db.get(Account, lic.account_id)
            prod_ = await db.get(Product, lic.product_id)
            store_ = await db.get(Store, lic.store_id) if lic.store_id else None
            if acc_ and acc_.phone:
                from app.notify import send_sms
                target = prod_.name + (f"({store_.name})" if store_ else "")
                await send_sms(acc_.phone, f"[플레이스마스터] {target} 이용이 승인되었습니다. "
                                           f"마이페이지에서 설치 파일을 받아 이용해 주세요. {settings.BASE_URL}/my")
                msg += " 승인 안내 문자를 보냈습니다."
        elif action == "grant":                  # 요금제 지급 (결제 없이)
            plan = await db.get(Plan, _int(f.get("plan_id")))
            if not plan or plan.product_id != lic.product_id:
                raise licensing.LicenseError("요금제를 선택해 주세요")
            await licensing.apply_plan(db, lic, plan, actor, months=_int(f.get("months")))
            msg = f"'{plan.name}'을 지급했습니다."
        elif action == "extend":
            months, days = _int(f.get("months"), 0), _int(f.get("days"), 0)
            base = licensing.aware(lic.expires_at) if lic.expires_at else None
            if base is None:
                raise licensing.LicenseError("무제한 이용권은 연장할 필요가 없어요. 기간을 정하려면 '만료일 지정'이나 '요금제 지급'을 쓰세요.")
            base = max(base, now_utc())
            new = licensing._add_months(base, months) + timedelta(days=days)
            await licensing.set_expiry(db, lic, new, actor, reason or f"+{months}개월 {days}일")
            if lic.status != LicenseStatus.ACTIVE:
                await licensing.set_status(db, lic, LicenseStatus.ACTIVE, actor, "연장")
            msg = "연장했습니다."
        elif action == "set_expiry":
            exp = _date(f.get("expires_at"))
            await licensing.set_expiry(db, lic, exp, actor, reason or "만료일 직접 지정")
            msg = "만료일을 " + (f"{f.get('expires_at')}로" if exp else "무제한으로") + " 바꿨습니다."
        elif action == "suspend":
            await licensing.set_status(db, lic, LicenseStatus.SUSPENDED, actor, reason)
            msg = "정지했습니다."
        elif action == "resume":
            await licensing.set_status(db, lic, LicenseStatus.ACTIVE, actor, reason)
            msg = "정지를 풀었습니다."
        elif action == "cancel":
            lic.autopay = False
            lic.next_charge_at = None
            await licensing.set_status(db, lic, LicenseStatus.CANCELLED, actor, reason)
            msg = "해지했습니다."
        elif action == "device_reset":
            await licensing.reset_device(db, lic, actor, by_owner=False)
            msg = "PC 등록을 해제했습니다."
        elif action == "autopay_off":
            lic.autopay = False
            lic.next_charge_at = None
            await licensing.log(db, lic, actor, "autopay_off", reason=reason)
            msg = "자동결제를 껐습니다."
        else:
            raise licensing.LicenseError("알 수 없는 작업")
        await db.commit()
        await _sync_plma(db, lic)
        flash(request, msg)
    except licensing.LicenseError as e:
        await db.rollback()
        flash(request, str(e), "err")
    return RedirectResponse(url(f"/ops/accounts/{account_id}#lic{lid}"), status_code=303)


async def _sync_plma(db: AsyncSession, lic: License):
    """플마 이용권이면 플마 프로그램이 보는 Firestore 갱신 (서비스 계정 키 있을 때)"""
    from app import firebase
    product = await db.get(Product, lic.product_id)
    if product.code != "plma" or not firebase.sa_available():
        return
    acc = await db.get(Account, lic.account_id)
    exp = "2099-12-31" if lic.expires_at is None else \
        licensing.grace_end(lic.expires_at).astimezone(KST).strftime("%Y-%m-%d")
    try:
        await firebase.sync_plma_user(acc.firebase_uid, active=licensing.usable(lic), expires_at=exp,
                                      email=acc.email, name=acc.name, device_id=lic.device_id or "")
    except Exception:
        pass


# ───────────── 상품·요금제 ─────────────

@router.get("/products")
async def products_page(request: Request, db: AsyncSession = Depends(get_db)):
    op = await require_operator(request, db)
    products = (await db.execute(select(Product).order_by(Product.sort))).scalars().all()
    view = []
    for p in products:
        plans = (await db.execute(select(Plan).where(Plan.product_id == p.id).order_by(Plan.sort))).scalars().all()
        view.append({"p": p, "plans": [{"plan": pl, "list": list_price(p, pl), "price": plan_price(p, pl),
                                        "monthly": effective_monthly(p, pl)} for pl in plans],
                     "warnings": plan_rule_warnings(p, plans)})
    max_pct = await orders.get_setting(db, "max_discount_pct", 60)
    return render(request, "ops/products.html", op=op, view=view, PlanKind=PlanKind, max_pct=max_pct,
                  nav="products")


@router.post("/products/{pid}")
async def product_save(request: Request, pid: int, db: AsyncSession = Depends(get_db)):
    await require_operator(request, db)
    p = await db.get(Product, pid)
    f = await request.form()
    p.name = str(f.get("name", p.name)).strip() or p.name
    p.tagline = str(f.get("tagline", "")).strip()
    p.monthly_price = _int(f.get("monthly_price"), p.monthly_price)
    p.signup_policy = SignupPolicy(f.get("signup_policy", p.signup_policy.value))
    p.download_url = str(f.get("download_url", "")).strip()
    p.active = bool(f.get("active"))
    await db.commit()
    flash(request, f"{p.name} 설정을 저장했습니다.")
    return RedirectResponse(url("/ops/products"), status_code=303)


@router.post("/plans")
async def plan_save(request: Request, db: AsyncSession = Depends(get_db)):
    await require_operator(request, db)
    f = await request.form()
    pid = _int(f.get("id"))
    plan = await db.get(Plan, pid) if pid else Plan(product_id=_int(f.get("product_id")))
    if f.get("delete") and pid:
        used = (await db.execute(select(func.count(License.id)).where(License.plan_id == pid))).scalar()
        if used:
            plan.public = False
            flash(request, f"사용 중인 이용권이 {used}개 있어 삭제 대신 '판매 중지'로 바꿨습니다.")
        else:
            await db.delete(plan)
            flash(request, "요금제를 삭제했습니다.")
        await db.commit()
        return RedirectResponse(url("/ops/products"), status_code=303)
    plan.name = str(f.get("name", "")).strip() or "요금제"
    plan.kind = PlanKind(f.get("kind", "prepaid"))
    plan.months = _int(f.get("months"))
    plan.discount_pct = max(0, min(95, _int(f.get("discount_pct"), 0)))
    plan.lifetime_months = _int(f.get("lifetime_months"), 36) or 36
    plan.price_override = _int(f.get("price_override"))
    plan.badge = str(f.get("badge", "")).strip()[:30]
    plan.public = bool(f.get("public"))
    plan.sort = _int(f.get("sort"), 0)
    if plan.kind in (PlanKind.PREPAID, PlanKind.MONTHLY) and not plan.months:
        flash(request, "개월 수를 입력해 주세요.", "err")
        return RedirectResponse(url("/ops/products"), status_code=303)
    if not pid:
        db.add(plan)
    await db.commit()
    flash(request, f"'{plan.name}' 요금제를 저장했습니다.")
    return RedirectResponse(url("/ops/products"), status_code=303)


@router.post("/settings")
async def settings_save(request: Request, db: AsyncSession = Depends(get_db)):
    await require_operator(request, db)
    f = await request.form()
    await orders.put_setting(db, "max_discount_pct", max(0, min(95, _int(f.get("max_discount_pct"), 60))))
    await db.commit()
    flash(request, "할인 한도를 저장했습니다.")
    return RedirectResponse(url("/ops/products"), status_code=303)


# ───────────── 프로모션 ─────────────

@router.get("/promotions")
async def promotions_page(request: Request, db: AsyncSession = Depends(get_db)):
    op = await require_operator(request, db)
    promos = (await db.execute(select(Promotion).order_by(Promotion.id.desc()))).scalars().all()
    products = (await db.execute(select(Product).order_by(Product.sort))).scalars().all()
    max_pct = await orders.get_setting(db, "max_discount_pct", 60)
    return render(request, "ops/promotions.html", op=op, promos=promos, products=products, max_pct=max_pct,
                  PlanKind=PlanKind, nav="promos")


@router.post("/promotions")
async def promotion_save(request: Request, db: AsyncSession = Depends(get_db)):
    await require_operator(request, db)
    f = await request.form()
    pid = _int(f.get("id"))
    promo = await db.get(Promotion, pid) if pid else Promotion()
    if f.get("delete") and pid:
        promo.active = False
        await db.commit()
        flash(request, "프로모션을 종료했습니다.")
        return RedirectResponse(url("/ops/promotions"), status_code=303)
    code = str(f.get("code", "")).strip().upper() or None
    if code:
        dup = (await db.execute(select(Promotion).where(Promotion.code == code, Promotion.id != (pid or 0)))).first()
        if dup:
            flash(request, f"쿠폰 코드 {code}는 이미 있습니다.", "err")
            return RedirectResponse(url("/ops/promotions"), status_code=303)
    promo.name = str(f.get("name", "")).strip() or "프로모션"
    promo.code = code
    promo.kind = f.get("kind", "percent")
    promo.value = max(0, _int(f.get("value"), 0))
    if promo.kind != "amount":
        promo.value = min(promo.value, 95)
    promo.product_codes = f.getlist("product_codes")
    promo.plan_kinds = f.getlist("plan_kinds")
    promo.min_products = max(1, _int(f.get("min_products"), 2 if promo.kind == "bundle" else 1))
    s = (f.get("starts_at") or "").strip()
    promo.starts_at = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=KST).astimezone(timezone.utc) if s else None
    promo.ends_at = _date(f.get("ends_at"))
    promo.max_uses = _int(f.get("max_uses"))
    promo.active = bool(f.get("active"))
    if not pid:
        db.add(promo)
    await db.commit()
    flash(request, f"'{promo.name}'을 저장했습니다.")
    return RedirectResponse(url("/ops/promotions"), status_code=303)


# ───────────── 결제 ─────────────

@router.get("/orders")
async def orders_page(request: Request, status: str = "", db: AsyncSession = Depends(get_db)):
    op = await require_operator(request, db)
    stmt = select(Order).order_by(Order.created_at.desc())
    if status:
        stmt = stmt.where(Order.status == OrderStatus(status))
    rows = (await db.execute(stmt.limit(300))).scalars().all()
    for o in rows:
        await db.refresh(o, ["account"])
    return render(request, "ops/orders.html", op=op, orders=rows, status=status,
                  public_discounts=orders.public_discounts, nav="orders")


@router.post("/orders/{oid}")
async def order_action(request: Request, oid: str, db: AsyncSession = Depends(get_db)):
    op = await require_operator(request, db)
    order = await db.get(Order, oid)
    if not order:
        raise HTTPException(404)
    f = await request.form()
    action = f.get("action")
    if action == "mark_paid" and order.status in (OrderStatus.PENDING, OrderStatus.FAILED):
        # 계좌이체 등 수동 결제 확인
        order.method = "manual"
        await orders.fulfill(db, order, f"operator:{op.email}")
        await db.commit()
        flash(request, "입금 확인 처리했습니다. 이용권이 적용되었습니다.")
    elif action == "refund" and order.status == OrderStatus.PAID:
        try:
            if order.toss_payment_key:
                await payments.cancel_payment(order.toss_payment_key, str(f.get("reason") or "운영자 환불"))
            order.status = OrderStatus.REFUNDED
            # 환불 시 이용권은 운영자가 직접 조정 (자동 회수하지 않음)
            await db.commit()
            flash(request, "환불했습니다. 필요하면 회원 화면에서 이용권 기간을 조정해 주세요.")
        except payments.TossError as e:
            flash(request, f"환불 실패: {e}", "err")
    elif action == "cancel" and order.status == OrderStatus.PENDING:
        order.status = OrderStatus.CANCELLED
        await db.commit()
        flash(request, "주문을 취소했습니다.")
    back = request.query_params.get("back") or "/ops/orders"
    return RedirectResponse(url(back if back.startswith("/ops") else "/ops/orders"), status_code=303)


# ───────────── 알림 기록 ─────────────

@router.get("/notifications")
async def notifications(request: Request, db: AsyncSession = Depends(get_db)):
    op = await require_operator(request, db)
    rows = (await db.execute(select(NotificationLog).order_by(NotificationLog.created_at.desc()).limit(300))).scalars().all()
    return render(request, "ops/notifications.html", op=op, rows=rows, nav="notify")
