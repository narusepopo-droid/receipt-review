"""
프로그램용 이용권 API

POST /api/v1/license/login   이메일·비밀번호(또는 Firebase ID 토큰) + 상품 + PC → 이용권 확인·PC 등록, 확인 토큰 발급
POST /api/v1/license/check   확인 토큰 + PC → 지금도 사용 가능한지 (프로그램이 주기적으로 호출)
POST /internal/review-store  영수증리뷰 서버 → 매장 이용 가능 여부 (서버끼리)
"""
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import firebase, licensing
from app.config import settings
from app.db import get_db
from app.models import Account, License, Product, Store, Unit
from app.routers.auth import _ip, _limited, upsert_account
from app.web import KST

router = APIRouter()
TOKEN_MAX_AGE = 60 * 60 * 24 * 30   # 30일 (매 확인 때 새로 발급)


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt="license-token")


def issue_token(lic: License) -> str:
    return _signer().dumps({"l": lic.id, "d": lic.device_id})


def _fail(message: str, code: str, status: int = 403):
    return JSONResponse({"ok": False, "code": code, "message": message}, status_code=status)


def _license_payload(lic: License, product: Product, store: Store = None) -> dict:
    st = licensing.state(lic)
    exp = lic.expires_at
    return {
        "ok": True, "state": st, "product": product.code,
        "expires_at": licensing.aware(exp).astimezone(KST).strftime("%Y-%m-%d") if exp else None,
        "usable_until": licensing.grace_end(exp).astimezone(KST).isoformat() if exp else None,
        "days_left": licensing.days_left(lic),
        "unlimited": exp is None,
        "store": {"id": store.id, "name": store.name, "review_store_id": store.review_store_id,
                  "review_store_code": store.review_store_code} if store else None,
        "token": issue_token(lic),
        "message": "유예 기간입니다. 내일까지 연장하지 않으면 사용이 중지됩니다." if st == "grace" else "",
    }


async def _usable_or_fail(lic: License):
    st = licensing.state(lic)
    if st == "pending":
        return _fail("담당자 승인 또는 결제 후 사용할 수 있습니다. 마이페이지를 확인해 주세요.", "pending")
    if st == "expired":
        return _fail("이용 기간이 끝났습니다. 마이페이지에서 연장해 주세요.", "expired")
    if st in ("suspended", "cancelled"):
        return _fail("사용이 중지된 이용권입니다. 고객센터로 문의해 주세요.", st)
    return None


@router.post("/api/v1/license/login")
async def license_login(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    code = (body.get("product") or "").strip()
    device_id = (body.get("device_id") or "").strip()
    device_name = (body.get("device_name") or "").strip()
    product = (await db.execute(select(Product).where(Product.code == code))).scalar_one_or_none()
    if not product:
        return _fail("알 수 없는 상품입니다", "bad_product", 400)

    # 1) 로그인: Firebase ID 토큰(플마) 또는 이메일·비밀번호
    if body.get("id_token"):
        info = await firebase.verify_id_token(body["id_token"])
        if not info:
            return _fail("로그인이 만료되었습니다. 다시 로그인해 주세요.", "bad_token", 401)
        acc = await upsert_account(db, info["uid"], info["email"])
        res = {}
    else:
        email = (body.get("email") or "").strip().lower()
        if _limited(f"api-login:{_ip(request)}:{email}", 10, 600):
            return _fail("로그인 시도가 너무 많습니다. 10분 후 다시 시도해 주세요.", "rate_limited", 429)
        try:
            res = await firebase.sign_in(email, body.get("password") or "")
        except firebase.FirebaseError as e:
            from app.legacy import try_migrate_review_owner
            migrated = await try_migrate_review_owner(db, email, body.get("password") or "") \
                if code == "receipt_review" else None
            if not migrated:
                return _fail(str(e), "bad_login", 401)
            res = {"localId": migrated.firebase_uid, "email": migrated.email}
        acc = await upsert_account(db, res["localId"], res.get("email", email))
    if acc.blocked:
        return _fail("사용이 중지된 계정입니다.", "blocked")
    if code == "plma":
        from app.plma import import_plma
        tok = body.get("id_token") or (res.get("idToken") if not body.get("id_token") else None)
        await import_plma(db, acc, acc.firebase_uid, tok)

    # 2) 이용권 찾기 (매장 단위면 매장 선택)
    lics = (await db.execute(select(License).where(License.account_id == acc.id, License.product_id == product.id)
                             .order_by(License.id))).scalars().all()
    if not lics:
        await db.commit()
        return _fail(f"{product.name} 이용권이 없습니다. 마이페이지에서 신청해 주세요.", "no_license")
    store = None
    if product.unit == Unit.STORE:
        store_id = body.get("store_id")
        if store_id:
            lic = next((l for l in lics if l.store_id == int(store_id)), None)
            if not lic:
                return _fail("선택한 매장의 이용권이 없습니다", "no_license")
        else:
            candidates = []
            for l in lics:
                s = await db.get(Store, l.store_id) if l.store_id else None
                if s and not s.archived:
                    candidates.append((l, s))
            # 이 PC가 이미 등록된 매장이 있으면 그 매장, 매장이 하나면 그 매장, 여러 개면 선택 요청
            same_pc = [c for c in candidates if c[0].device_id == device_id and device_id]
            if same_pc:
                lic, store = same_pc[0]
            elif len(candidates) == 1:
                lic, store = candidates[0]
            else:
                await db.commit()
                return JSONResponse({"ok": False, "code": "choose_store", "message": "매장을 선택해 주세요",
                                     "stores": [{"id": s.id, "name": s.name, "state": licensing.state(l),
                                                 "pc": l.device_name or ""} for l, s in candidates]})
        store = store or await db.get(Store, lic.store_id)
    else:
        lic = lics[0]

    bad = await _usable_or_fail(lic)
    if bad:
        await db.commit()
        return bad
    try:
        await licensing.bind_device(db, lic, device_id, device_name)
    except licensing.LicenseError as e:
        await db.commit()
        return _fail(str(e), e.code)
    await db.commit()
    return JSONResponse(_license_payload(lic, product, store))


@router.post("/api/v1/license/check")
async def license_check(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    try:
        data = _signer().loads(body.get("token") or "", max_age=TOKEN_MAX_AGE)
    except SignatureExpired:
        return _fail("다시 로그인해 주세요", "token_expired", 401)
    except BadSignature:
        return _fail("다시 로그인해 주세요", "bad_token", 401)
    lic = await db.get(License, data["l"])
    if not lic:
        return _fail("이용권을 찾을 수 없습니다", "no_license")
    acc = await db.get(Account, lic.account_id)
    if acc.blocked:
        return _fail("사용이 중지된 계정입니다.", "blocked")
    device_id = (body.get("device_id") or "").strip()
    if lic.device_id and device_id != lic.device_id:
        return _fail(f"이 이용권은 다른 PC({lic.device_name or '등록된 PC'})에서 사용 중입니다.", "device_mismatch")
    bad = await _usable_or_fail(lic)
    if bad:
        return bad
    if not lic.device_id and device_id:
        await licensing.bind_device(db, lic, device_id, body.get("device_name") or "")
        await db.commit()
    product = await db.get(Product, lic.product_id)
    store = await db.get(Store, lic.store_id) if lic.store_id else None
    return JSONResponse(_license_payload(lic, product, store))


# ───────────── 서버끼리 ─────────────

def _check_internal(secret: str):
    if not secret or not hmac.compare_digest(secret, settings.INTERNAL_SECRET):
        raise HTTPException(status_code=403)


@router.post("/internal/review-store")
async def internal_review_store(request: Request, x_internal_secret: str = Header(""),
                                db: AsyncSession = Depends(get_db)):
    """영수증리뷰 서버가 매장 이용 가능 여부를 물을 때. 계정 서버에 연결 안 된 매장은 'unknown'(제한 안 함)"""
    _check_internal(x_internal_secret)
    body = await request.json()
    store = (await db.execute(select(Store).where(Store.review_store_id == int(body["review_store_id"]))))\
        .scalars().first()
    if not store:
        return {"state": "unknown", "usable": True}
    product = (await db.execute(select(Product).where(Product.code == "receipt_review"))).scalar_one()
    lic = (await db.execute(select(License).where(License.store_id == store.id,
                                                  License.product_id == product.id))).scalars().first()
    if not lic:
        return {"state": "none", "usable": False}
    return {"state": licensing.state(lic), "usable": licensing.usable(lic),
            "expires_at": lic.expires_at.isoformat() if lic.expires_at else None}


@router.post("/internal/link-store")
async def internal_link_store(request: Request, x_internal_secret: str = Header(""),
                              db: AsyncSession = Depends(get_db)):
    """영수증리뷰 서버에서 매장을 만들면 계정 서버 매장과 연결"""
    _check_internal(x_internal_secret)
    body = await request.json()
    store = await db.get(Store, int(body["store_id"]))
    if not store:
        raise HTTPException(404)
    store.review_store_id = int(body["review_store_id"])
    store.review_store_code = body.get("review_store_code")
    await db.commit()
    return {"ok": True}


@router.post("/internal/owner-login")
async def internal_owner_login(request: Request, x_internal_secret: str = Header(""),
                               db: AsyncSession = Depends(get_db)):
    """영수증리뷰 점주웹 로그인 확인 (PC 등록 없음). 이메일·비밀번호 → 영수증리뷰 매장 목록"""
    _check_internal(x_internal_secret)
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    try:
        res = await firebase.sign_in(email, body.get("password") or "")
    except firebase.FirebaseError as e:
        from app.legacy import try_migrate_review_owner
        migrated = await try_migrate_review_owner(db, email, body.get("password") or "")
        if not migrated:
            return {"ok": False, "message": str(e)}
        res = {"localId": migrated.firebase_uid, "email": migrated.email}
    acc = await upsert_account(db, res["localId"], res.get("email", email))
    await db.commit()
    if acc.blocked:
        return {"ok": False, "message": "사용이 중지된 계정입니다."}
    product = (await db.execute(select(Product).where(Product.code == "receipt_review"))).scalar_one()
    lics = (await db.execute(select(License).where(License.account_id == acc.id, License.product_id == product.id)
                             .order_by(License.id))).scalars().all()
    stores = []
    for l in lics:
        s = await db.get(Store, l.store_id) if l.store_id else None
        if s and not s.archived:
            stores.append({"id": s.id, "name": s.name, "review_store_id": s.review_store_id,
                           "state": licensing.state(l), "usable": licensing.usable(l)})
    return {"ok": True, "email": acc.email, "stores": stores}
