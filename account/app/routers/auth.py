"""가입 · 로그인 · 로그아웃 · 비밀번호 재설정 (Firebase)"""
import re
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import firebase, licensing
from app.config import settings
from app.db import get_db
from app.models import Account, Product, SignupPolicy, Store, Unit, now_utc
from app.web import current_account, flash, render, url

router = APIRouter()

_hits: dict = defaultdict(deque)


def _limited(key: str, limit: int, window: int) -> bool:
    now = time.time()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def _ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "-")


async def upsert_account(db: AsyncSession, uid: str, email: str, **fields) -> Account:
    email = email.strip().lower()
    acc = (await db.execute(select(Account).where(Account.firebase_uid == uid))).scalar_one_or_none() if uid else None
    if not acc:
        acc = (await db.execute(select(Account).where(Account.email == email))).scalar_one_or_none()
    if not acc:
        acc = Account(email=email, firebase_uid=uid or None)
        db.add(acc)
    if uid and not acc.firebase_uid:
        acc.firebase_uid = uid
    for k, v in fields.items():
        if v:
            setattr(acc, k, v)
    if email in settings.ops_emails:
        acc.is_operator = True
    acc.last_login_at = now_utc()
    await db.flush()
    return acc


@router.get("/login")
async def login_page(request: Request, next: str = "", db: AsyncSession = Depends(get_db)):
    if await current_account(request, db):
        return RedirectResponse(url(next or "/my"), status_code=303)
    return render(request, "auth/login.html", next=next)


@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form(""),
                db: AsyncSession = Depends(get_db)):
    email = email.strip().lower()
    if _limited(f"login:{_ip(request)}:{email}", 5, 600):
        return render(request, "auth/login.html", next=next, email=email,
                      error="로그인 시도가 너무 많습니다. 10분 후 다시 시도해 주세요.")
    try:
        res = await firebase.sign_in(email, password)
    except firebase.FirebaseError as e:
        # 예전 영수증리뷰 점주 계정이면 자동 이전
        from app.legacy import try_migrate_review_owner
        acc = await try_migrate_review_owner(db, email, password)
        if not acc:
            return render(request, "auth/login.html", next=next, email=email, error=str(e))
        res = {"localId": acc.firebase_uid, "email": acc.email}
    acc = await upsert_account(db, res["localId"], res.get("email", email))
    if acc.blocked:
        return render(request, "auth/login.html", next=next, email=email, error="사용이 중지된 계정입니다.")
    if res.get("idToken"):
        from app.plma import import_plma
        await import_plma(db, acc, res["localId"], res["idToken"])
    await db.commit()
    request.session.clear()
    request.session["aid"] = acc.id
    dest = next if next.startswith("/") and not next.startswith("//") else ("/ops" if acc.is_operator else "/my")
    return RedirectResponse(url(dest), status_code=303)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url("/login"), status_code=303)


@router.get("/signup")
async def signup_page(request: Request, product: str = "", db: AsyncSession = Depends(get_db)):
    if await current_account(request, db):
        flash(request, "이미 로그인되어 있어요. 다른 상품은 아래에서 바로 신청할 수 있어요.", "info")
        return RedirectResponse(url("/my"), status_code=303)
    products = (await db.execute(select(Product).where(Product.active.is_(True)).order_by(Product.sort))).scalars().all()
    return render(request, "auth/signup.html", products=products, pre=product, form={})


@router.post("/signup")
async def signup(request: Request, db: AsyncSession = Depends(get_db)):
    form = dict(await request.form())
    products = (await db.execute(select(Product).where(Product.active.is_(True)).order_by(Product.sort))).scalars().all()
    chosen = [p for p in products if form.get(f"p_{p.code}")]
    email = (form.get("email") or "").strip().lower()
    phone = re.sub(r"\D", "", form.get("phone") or "")
    errors = []
    if not form.get("name", "").strip():
        errors.append("이름을 입력해 주세요")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors.append("이메일을 정확히 입력해 주세요")
    if not re.fullmatch(r"01[016789]\d{7,8}", phone):
        errors.append("휴대폰 번호를 정확히 입력해 주세요 (만료 안내 문자를 보내드려요)")
    if len(form.get("password") or "") < 8:
        errors.append("비밀번호는 8자 이상으로 정해 주세요")
    if form.get("password") != form.get("password2"):
        errors.append("비밀번호 확인이 일치하지 않습니다")
    if not chosen:
        errors.append("이용할 상품을 하나 이상 선택해 주세요")
    if any(p.unit == Unit.STORE for p in chosen) and not form.get("store_name", "").strip():
        errors.append("영수증리뷰를 쓰실 매장 이름을 입력해 주세요")
    if not form.get("agree"):
        errors.append("이용약관·개인정보 처리에 동의해 주세요")
    if _limited(f"signup:{_ip(request)}", 10, 3600):
        errors.append("가입 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요")
    if errors:
        return render(request, "auth/signup.html", products=products, pre="", form=form, errors=errors)

    try:
        res = await firebase.sign_up(email, form["password"])
    except firebase.FirebaseError as e:
        return render(request, "auth/signup.html", products=products, pre="", form=form, errors=[str(e)])

    acc = await upsert_account(db, res["localId"], email, name=form["name"].strip(), phone=phone,
                               company=form.get("company", "").strip(), biz_no=form.get("biz_no", "").strip())
    store = None
    if any(p.unit == Unit.STORE for p in chosen):
        store = Store(account_id=acc.id, name=form["store_name"].strip(), biz_no=form.get("biz_no", "").strip(),
                      phone=phone)
        db.add(store)
        await db.flush()
    need_payment = []
    for p in chosen:
        lic = await licensing.get_or_create(db, acc, p, store if p.unit == Unit.STORE else None)
        if p.signup_policy == SignupPolicy.PAYMENT:
            need_payment.append((p, lic))
    await db.commit()
    request.session.clear()
    request.session["aid"] = acc.id
    if need_payment:
        p, lic = need_payment[0]
        return RedirectResponse(url(f"/my/buy/{lic.id}"), status_code=303)
    flash(request, "가입이 완료되었습니다. 담당자 승인 후 바로 이용하실 수 있어요.", "ok")
    return RedirectResponse(url("/my"), status_code=303)


@router.get("/terms")
async def terms(request: Request):
    return render(request, "auth/terms.html")


@router.get("/privacy")
async def privacy(request: Request):
    return render(request, "auth/privacy.html")


@router.get("/reset")
async def reset_page(request: Request):
    return render(request, "auth/reset.html")


@router.post("/reset")
async def reset(request: Request, email: str = Form(...)):
    if not _limited(f"reset:{_ip(request)}", 5, 3600):
        try:
            await firebase.send_password_reset(email.strip().lower())
        except firebase.FirebaseError:
            pass   # 가입 여부를 알려주지 않음
    return render(request, "auth/reset.html", sent=True)
