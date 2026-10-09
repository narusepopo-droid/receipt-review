"""점주 마이페이지"""
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import licensing, orders, payments
from app.config import settings
from app.db import get_db
from app.models import (Account, BillingKey, License, LicenseStatus, Order, OrderStatus, Plan, PlanKind, Product,
                        SignupPolicy, Store, Unit)
from app.pricing import Line, effective_monthly, list_price, plan_price
from app.web import flash, render, require_account, url

router = APIRouter(prefix="/my")


async def _my_license(db: AsyncSession, acc: Account, license_id: int) -> License:
    lic = await db.get(License, license_id)
    if not lic or lic.account_id != acc.id:
        raise HTTPException(status_code=404, detail="이용권을 찾을 수 없습니다")
    return lic


@router.get("")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    products = (await db.execute(select(Product).where(Product.active.is_(True)).order_by(Product.sort))).scalars().all()
    lics = (await db.execute(select(License).where(License.account_id == acc.id).order_by(License.id))).scalars().all()
    stores = (await db.execute(select(Store).where(Store.account_id == acc.id, Store.archived.is_(False))
                               .order_by(Store.id))).scalars().all()
    for l in lics:
        await db.refresh(l, ["product", "store", "plan"])
    by_product = {p.id: [l for l in lics if l.product_id == p.id] for p in products}
    return render(request, "my/dashboard.html", acc=acc, products=products, by_product=by_product, stores=stores,
                  Unit=Unit)


@router.get("/stores/new")
async def store_new(request: Request, db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    return render(request, "my/store_new.html", acc=acc)


@router.post("/stores")
async def store_create(request: Request, name: str = Form(...), biz_no: str = Form(""), address: str = Form(""),
                       db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    if not name.strip():
        return render(request, "my/store_new.html", acc=acc, error="매장 이름을 입력해 주세요")
    store = Store(account_id=acc.id, name=name.strip(), biz_no=biz_no.strip(), address=address.strip())
    db.add(store)
    await db.flush()
    target = None
    for p in (await db.execute(select(Product).where(Product.unit == Unit.STORE, Product.active.is_(True)))).scalars():
        lic = await licensing.get_or_create(db, acc, p, store)
        target = target or (lic if p.signup_policy == SignupPolicy.PAYMENT else None)
    await db.commit()
    if target:
        return RedirectResponse(url(f"/my/buy/{target.id}"), status_code=303)
    flash(request, f"'{store.name}' 매장을 추가했습니다. 담당자 확인 후 이용하실 수 있어요.")
    return RedirectResponse(url("/my"), status_code=303)


@router.post("/products/{code}/apply")
async def apply_product(request: Request, code: str, db: AsyncSession = Depends(get_db)):
    """계정 단위 상품 이용 신청 (예: 플마)"""
    acc = await require_account(request, db)
    product = (await db.execute(select(Product).where(Product.code == code))).scalar_one_or_none()
    if not product or product.unit != Unit.ACCOUNT:
        raise HTTPException(404)
    lic = await licensing.get_or_create(db, acc, product, None)
    await db.commit()
    if product.signup_policy == SignupPolicy.PAYMENT:
        return RedirectResponse(url(f"/my/buy/{lic.id}"), status_code=303)
    flash(request, f"{product.name} 이용을 신청했습니다. 담당자 승인 후 이용하실 수 있어요.")
    return RedirectResponse(url("/my"), status_code=303)


# ───────────── 구매 ─────────────

def _plan_view(product: Product, plan: Plan) -> dict:
    lp, pp = list_price(product, plan), plan_price(product, plan)
    return {"plan": plan, "list": lp, "price": pp, "monthly": effective_monthly(product, plan),
            "save_pct": round((1 - pp / lp) * 100) if lp else 0}


@router.get("/buy/{license_id}")
async def buy_page(request: Request, license_id: int, db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    lic = await _my_license(db, acc, license_id)
    await db.refresh(lic, ["product", "store", "plan"])
    plans = (await db.execute(select(Plan).where(Plan.product_id == lic.product_id, Plan.public.is_(True))
                              .order_by(Plan.sort))).scalars().all()
    # 함께 사면 할인 받을 수 있는 다른 상품 이용권
    others = (await db.execute(select(License).where(License.account_id == acc.id, License.id != lic.id,
                                                     License.product_id != lic.product_id))).scalars().all()
    for o in others:
        await db.refresh(o, ["product", "store"])
    other_plans = {}
    for o in others:
        other_plans[o.id] = [_plan_view(o.product, p) for p in (await db.execute(
            select(Plan).where(Plan.product_id == o.product_id, Plan.public.is_(True)).order_by(Plan.sort))).scalars()]
    bk = await orders.active_billing_key(db, acc.id)
    return render(request, "my/buy.html", acc=acc, lic=lic, plans=[_plan_view(lic.product, p) for p in plans],
                  others=others, other_plans=other_plans, billing_key=bk, toss=settings.toss_enabled,
                  PlanKind=PlanKind)


async def _lines_from(db: AsyncSession, acc: Account, data: dict) -> list[Line]:
    lines = []
    for item in data.get("items", []):
        lic = await _my_license(db, acc, int(item["license_id"]))
        plan = await db.get(Plan, int(item["plan_id"]))
        if not plan or plan.product_id != lic.product_id or not plan.public:
            raise HTTPException(400, "요금제를 다시 선택해 주세요")
        product = await db.get(Product, lic.product_id)
        lines.append(Line(product=product, plan=plan, store_id=lic.store_id))
    if not lines:
        raise HTTPException(400, "요금제를 선택해 주세요")
    return lines


@router.post("/quote")
async def quote_api(request: Request, db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    data = await request.json()
    lines = await _lines_from(db, acc, data)
    q = await orders.quote(db, lines, data.get("promo_code"))
    return JSONResponse({
        "lines": [{"name": f"{l.product.name} · {l.plan.name}", "list": l.list_amount, "amount": l.amount,
                   "monthly": l.plan.kind == PlanKind.MONTHLY} for l in lines],
        "list_amount": q.list_amount, "discounts": q.discounts, "amount": q.amount, "promo_error": q.promo_error,
    })


@router.post("/checkout")
async def checkout(request: Request, db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    data = await request.json()
    lines = await _lines_from(db, acc, data)
    has_monthly = any(l.plan.kind == PlanKind.MONTHLY for l in lines)
    if has_monthly and len(lines) > 1:
        return JSONResponse({"error": "월 자동결제는 한 번에 하나씩 신청해 주세요"}, status_code=400)
    try:
        order, q = await orders.create_order(db, acc, lines, data.get("promo_code"),
                                             method="billing" if has_monthly else "card")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    if order.amount == 0:
        await orders.fulfill(db, order, "free")
        await db.commit()
        return JSONResponse({"done": True, "redirect": url("/my")})

    if not settings.toss_enabled:
        order.method = "manual"
        await db.commit()
        return JSONResponse({"done": True, "manual": True, "redirect": url(f"/my/orders?new={order.id}")})

    base = settings.BASE_URL.rstrip("/")
    await db.commit()
    if has_monthly:
        bk = await orders.active_billing_key(db, acc.id)
        if bk:   # 이미 등록된 카드로 바로 첫 달 청구
            return JSONResponse({"charge_now": True, "order_id": order.id})
        return JSONResponse({"toss": {
            "type": "billing", "clientKey": settings.TOSS_CLIENT_KEY, "customerKey": acc.toss_customer_key,
            "successUrl": f"{base}/my/billing/success?order={order.id}", "failUrl": f"{base}/my/pay/fail?order={order.id}"}})
    return JSONResponse({"toss": {
        "type": "payment", "clientKey": settings.TOSS_CLIENT_KEY, "amount": order.amount, "orderId": order.id,
        "orderName": order.title, "customerName": acc.name or acc.email, "customerEmail": acc.email,
        "successUrl": f"{base}/my/pay/success", "failUrl": f"{base}/my/pay/fail?order={order.id}"}})


@router.get("/pay/success")
async def pay_success(request: Request, paymentKey: str, orderId: str, amount: int,
                      db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    order = await db.get(Order, orderId)
    if not order or order.account_id != acc.id:
        raise HTTPException(404)
    if order.status == OrderStatus.PAID:
        return RedirectResponse(url(f"/my/orders?paid={order.id}"), status_code=303)
    if amount != order.amount:
        order.status = OrderStatus.FAILED
        order.fail_reason = "결제 금액 불일치"
        await db.commit()
        flash(request, "결제 금액이 맞지 않아 결제를 진행하지 않았습니다.", "err")
        return RedirectResponse(url("/my/orders"), status_code=303)
    try:
        res = await payments.confirm_payment(paymentKey, orderId, amount)
    except payments.TossError as e:
        order.status = OrderStatus.FAILED
        order.fail_reason = str(e)[:300]
        await db.commit()
        flash(request, f"결제가 완료되지 않았습니다: {e}", "err")
        return RedirectResponse(url("/my/orders"), status_code=303)
    await orders.fulfill(db, order, "payment", paymentKey, (res.get("receipt") or {}).get("url"))
    await db.commit()
    flash(request, "결제가 완료되었습니다. 바로 이용하실 수 있어요.")
    return RedirectResponse(url(f"/my/orders?paid={order.id}"), status_code=303)


@router.get("/pay/fail")
async def pay_fail(request: Request, order: str = "", message: str = "", db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    o = await db.get(Order, order) if order else None
    if o and o.account_id == acc.id and o.status == OrderStatus.PENDING:
        o.status = OrderStatus.CANCELLED
        o.fail_reason = message[:300]
        await db.commit()
    flash(request, f"결제가 취소되었습니다. {message}".strip(), "err")
    return RedirectResponse(url("/my"), status_code=303)


async def _charge_first_month(db: AsyncSession, acc: Account, order: Order, bk: BillingKey):
    res = await payments.charge_billing(payments.decrypt(bk.billing_key_enc), acc.toss_customer_key,
                                        order.amount, order.id, order.title)
    await orders.fulfill(db, order, "billing", res.get("paymentKey"), (res.get("receipt") or {}).get("url"))


@router.get("/billing/success")
async def billing_success(request: Request, customerKey: str, authKey: str, order: str,
                          db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    o = await db.get(Order, order)
    if not o or o.account_id != acc.id or customerKey != acc.toss_customer_key:
        raise HTTPException(404)
    try:
        res = await payments.issue_billing_key(authKey, customerKey)
        for old in (await db.execute(select(BillingKey).where(BillingKey.account_id == acc.id))).scalars():
            old.active = False
        card = res.get("card") or {}
        bk = BillingKey(account_id=acc.id, billing_key_enc=payments.encrypt(res["billingKey"]),
                        card_company=res.get("cardCompany") or card.get("issuerCode", ""),
                        card_number=res.get("cardNumber") or card.get("number", ""))
        db.add(bk)
        await db.flush()
        await _charge_first_month(db, acc, o, bk)
    except payments.TossError as e:
        o.status = OrderStatus.FAILED
        o.fail_reason = str(e)[:300]
        await db.commit()
        flash(request, f"카드 등록 또는 결제에 실패했습니다: {e}", "err")
        return RedirectResponse(url("/my/orders"), status_code=303)
    await db.commit()
    flash(request, "월 자동결제가 시작되었습니다. 매월 같은 날 자동으로 결제돼요.")
    return RedirectResponse(url(f"/my/orders?paid={o.id}"), status_code=303)


@router.post("/charge-now/{order_id}")
async def charge_now(request: Request, order_id: str, db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    o = await db.get(Order, order_id)
    bk = await orders.active_billing_key(db, acc.id)
    if not o or o.account_id != acc.id or not bk:
        raise HTTPException(404)
    try:
        await _charge_first_month(db, acc, o, bk)
    except payments.TossError as e:
        o.status = OrderStatus.FAILED
        o.fail_reason = str(e)[:300]
        await db.commit()
        return JSONResponse({"error": f"결제 실패: {e}"}, status_code=400)
    await db.commit()
    return JSONResponse({"done": True, "redirect": url(f"/my/orders?paid={o.id}")})


# ───────────── 이용권 관리 ─────────────

@router.post("/licenses/{license_id}/device-reset")
async def device_reset(request: Request, license_id: int, db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    lic = await _my_license(db, acc, license_id)
    try:
        await licensing.reset_device(db, lic, f"owner:{acc.email}", by_owner=True)
        await db.commit()
        flash(request, "PC 등록을 해제했습니다. 새 PC에서 로그인하면 그 PC가 등록돼요.")
    except licensing.LicenseError as e:
        flash(request, str(e), "err")
    return RedirectResponse(url("/my"), status_code=303)


@router.post("/licenses/{license_id}/autopay-cancel")
async def autopay_cancel(request: Request, license_id: int, db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    lic = await _my_license(db, acc, license_id)
    if lic.autopay:
        lic.autopay_cancel_requested = True
        await licensing.log(db, lic, f"owner:{acc.email}", "autopay_cancel_requested")
        await db.commit()
        end = lic.commitment_ends_at
        if end and licensing.aware(end) > licensing.now_utc():
            flash(request, f"해지를 신청했습니다. 약정 기간({licensing.aware(end).astimezone(licensing.KST):%Y.%m.%d})까지는 "
                           "매월 결제되고, 그 뒤 자동결제가 멈춥니다.")
        else:
            flash(request, "자동결제를 해지했습니다. 이미 결제한 기간까지는 계속 이용하실 수 있어요.")
    return RedirectResponse(url("/my"), status_code=303)


@router.get("/download/{license_id}")
async def download(request: Request, license_id: int, db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    lic = await _my_license(db, acc, license_id)
    product = await db.get(Product, lic.product_id)
    if not licensing.usable(lic):
        flash(request, "이용 중인 상품만 다운로드할 수 있어요.", "err")
        return RedirectResponse(url("/my"), status_code=303)
    if not product.download_url:
        flash(request, "다운로드 파일을 준비 중입니다. 고객센터로 문의해 주세요.", "err")
        return RedirectResponse(url("/my"), status_code=303)
    return RedirectResponse(product.download_url, status_code=303)


@router.get("/orders")
async def order_list(request: Request, db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    rows = (await db.execute(select(Order).where(Order.account_id == acc.id).order_by(Order.created_at.desc())
                             .limit(100))).scalars().all()
    return render(request, "my/orders.html", acc=acc, orders=rows, public_discounts=orders.public_discounts)


@router.get("/profile")
async def profile(request: Request, db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    bk = await orders.active_billing_key(db, acc.id)
    return render(request, "my/profile.html", acc=acc, billing_key=bk)


@router.post("/profile")
async def profile_save(request: Request, name: str = Form(""), phone: str = Form(""), company: str = Form(""),
                       biz_no: str = Form(""), db: AsyncSession = Depends(get_db)):
    acc = await require_account(request, db)
    digits = re.sub(r"\D", "", phone)
    if digits and not re.fullmatch(r"01[016789]\d{7,8}", digits):
        flash(request, "휴대폰 번호를 정확히 입력해 주세요", "err")
        return RedirectResponse(url("/my/profile"), status_code=303)
    acc.name, acc.phone, acc.company, acc.biz_no = name.strip(), digits, company.strip(), biz_no.strip()
    await db.commit()
    flash(request, "저장했습니다.")
    return RedirectResponse(url("/my/profile"), status_code=303)
