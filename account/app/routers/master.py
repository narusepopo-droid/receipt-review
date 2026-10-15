"""
마스터(광고토대왕) 전용 API — 플마 관리자 페이지(placemaster.co.kr/admin.html)가 호출

인증: 마스터의 Firebase 로그인 토큰 (Authorization: Bearer <idToken>), UID 가 MASTER_UID 인 경우만
- POST /api/v1/master/plma/delete     플마 회원 완전 삭제 (로그인 계정 + 회원 정보 + 분석 기록)
- POST /api/v1/master/plma/password   플마 회원 비밀번호 직접 변경 (마스터 화면에도 기록)
- GET  /api/v1/master/summary         영수증리뷰·이용권·결제 현황 숫자
- POST /api/v1/master/sso             통합 계정 운영 화면 / 영수증리뷰 운영 화면 바로 열기 (1분짜리 주소)
- GET  /ops/sso?t=                    통합 계정 운영 화면 자동 로그인
- GET  /api/v1/master/stores[/{id}]   매장 목록(포스 프로그램 실시간 사용 여부)·매장 요약
"""
import hmac
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import firebase, licensing
from app.config import settings
from app.db import get_db
from app.models import Account, License, Order, OrderStatus, Product, now_utc
from app.routers.api import PUBLIC_ORIGINS
from app.routers.auth import upsert_account
from app.web import url

router = APIRouter()
FS = "https://firestore.googleapis.com/v1/projects/{p}/databases/(default)/documents"
IDT = "https://identitytoolkit.googleapis.com/v1/projects/{p}/accounts:{a}"


def _cors(request: Request, resp: Response) -> Response:
    origin = request.headers.get("origin", "")
    if origin in PUBLIC_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
    return resp


def _json(request: Request, data: dict, status: int = 200) -> Response:
    return _cors(request, JSONResponse(data, status_code=status))


@router.options("/api/v1/master/{rest:path}")
async def preflight(request: Request, rest: str):
    resp = Response(status_code=204)
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    resp.headers["Access-Control-Max-Age"] = "600"
    return _cors(request, resp)


async def _master(request: Request) -> dict:
    auth = request.headers.get("authorization", "")
    tok = auth[7:] if auth.lower().startswith("bearer ") else ""
    info = await firebase.verify_id_token(tok) if tok else None
    if not info or not settings.MASTER_UID or not hmac.compare_digest(info.get("uid", ""), settings.MASTER_UID):
        raise HTTPException(status_code=403, detail="마스터 계정만 사용할 수 있습니다")
    return info


async def _admin_token() -> str:
    if not firebase.master_sa_available():
        raise HTTPException(status_code=503, detail="관리 키가 서버에 설정되지 않았습니다")
    return await firebase.master_access_token()


def _err(request: Request, e: HTTPException) -> Response:
    return _json(request, {"ok": False, "message": e.detail}, e.status_code)


# ───────────── 플마 회원 ─────────────

@router.post("/api/v1/master/plma/delete")
async def plma_delete(request: Request):
    try:
        await _master(request)
        body = await request.json()
        uid = str(body.get("uid", "")).strip()
        if not uid or uid == settings.MASTER_UID or "/" in uid:
            return _json(request, {"ok": False, "message": "삭제할 수 없는 회원입니다"}, 400)
        token = await _admin_token()
    except HTTPException as e:
        return _err(request, e)
    p = settings.FIREBASE_PROJECT_ID
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20) as c:
        # 분석 기록 → 회원 정보 → 로그인 계정 순서로 삭제
        r = await c.get(f"{FS.format(p=p)}/users/{uid}/hist?pageSize=300", headers=h)
        for d in (r.json().get("documents", []) if r.status_code == 200 else []):
            await c.delete(f"https://firestore.googleapis.com/v1/{d['name']}", headers=h)
        r1 = await c.delete(f"{FS.format(p=p)}/users/{uid}", headers=h)
        r2 = await c.post(IDT.format(p=p, a="delete"), headers=h, json={"localId": uid})
    auth_gone = r2.status_code == 200 or "USER_NOT_FOUND" in r2.text
    if r1.status_code not in (200, 404) or not auth_gone:
        return _json(request, {"ok": False, "message": "삭제 중 오류가 났습니다. 잠시 후 다시 시도해 주세요."}, 502)
    return _json(request, {"ok": True})


@router.post("/api/v1/master/plma/password")
async def plma_password(request: Request):
    try:
        await _master(request)
        body = await request.json()
        uid = str(body.get("uid", "")).strip()
        pw = str(body.get("password", ""))
        if not uid or "/" in uid:
            return _json(request, {"ok": False, "message": "회원을 찾을 수 없습니다"}, 400)
        if len(pw) < 6 or len(pw) > 100:
            return _json(request, {"ok": False, "message": "비밀번호는 6자 이상으로 정해 주세요"}, 400)
        token = await _admin_token()
    except HTTPException as e:
        return _err(request, e)
    p = settings.FIREBASE_PROJECT_ID
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(IDT.format(p=p, a="update"), headers=h, json={"localId": uid, "password": pw})
        if r.status_code != 200:
            msg = "로그인 계정이 없는 회원입니다" if "USER_NOT_FOUND" in r.text else "비밀번호를 바꾸지 못했습니다"
            return _json(request, {"ok": False, "message": msg}, 400)
        await c.patch(f"{FS.format(p=p)}/users/{uid}?updateMask.fieldPaths=initial_password", headers=h,
                      json={"fields": {"initial_password": {"stringValue": pw}}})
    return _json(request, {"ok": True})


# ───────────── 영수증리뷰·이용권·결제 현황 ─────────────

@router.get("/api/v1/master/summary")
async def summary(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        await _master(request)
    except HTTPException as e:
        return _err(request, e)
    now = now_utc()
    products = {p.id: p for p in (await db.execute(select(Product))).scalars()}
    lics = (await db.execute(select(License))).scalars().all()
    by = {}
    for l in lics:
        p = products.get(l.product_id)
        if not p:
            continue
        s = by.setdefault(p.code, {"name": p.name, "active": 0, "pending": 0, "soon": 0, "expired": 0})
        st = licensing.state(l, now)
        if st in ("active", "grace"):
            s["active"] += 1
            if l.expires_at and (licensing.days_left(l, now) or 999) <= 7:
                s["soon"] += 1
        elif st == "pending":
            s["pending"] += 1
        elif st in ("expired", "suspended"):
            s["expired"] += 1
    from app.web import KST
    month_start = now.astimezone(KST).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    data = {
        "accounts": (await db.execute(select(func.count(Account.id)))).scalar() or 0,
        "new_week": (await db.execute(select(func.count(Account.id)).where(
            Account.created_at >= now - timedelta(days=7)))).scalar() or 0,
        "licenses": by,
        "unpaid_orders": (await db.execute(select(func.count(Order.id)).where(
            Order.status == OrderStatus.PENDING))).scalar() or 0,
        "revenue_month": (await db.execute(select(func.coalesce(func.sum(Order.amount), 0)).where(
            Order.status == OrderStatus.PAID, Order.paid_at >= month_start))).scalar() or 0,
        "review": None,
    }
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{settings.REVIEW_API_URL}/internal/ops-summary",
                            headers={"X-Internal-Secret": settings.INTERNAL_SECRET})
        if r.status_code == 200:
            data["review"] = r.json()
    except Exception:
        pass
    return _json(request, {"ok": True, **data})


# ───────────── 운영 화면 바로 열기 ─────────────

def _sso_signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt="master-ops-sso")


@router.post("/api/v1/master/sso")
async def sso(request: Request):
    try:
        info = await _master(request)
    except HTTPException as e:
        return _err(request, e)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    acct = settings.BASE_URL.rstrip("/") + "/ops/sso?t=" + _sso_signer().dumps(
        {"u": info["uid"], "e": info.get("email", ""), "n": _safe_next(body.get("account_next"))})
    review = settings.REVIEW_PUBLIC_URL.rstrip("/") + "/ops/sso?t=" + URLSafeTimedSerializer(
        settings.INTERNAL_SECRET, salt="master-review-ops").dumps({"u": info["uid"], "n": _safe_next(body.get("review_next"))})
    return _json(request, {"ok": True, "account_ops": acct, "review_ops": review})


@router.get("/ops/sso")
async def ops_sso(request: Request, t: str = "", db: AsyncSession = Depends(get_db)):
    try:
        d = _sso_signer().loads(t, max_age=60)
    except (BadSignature, SignatureExpired):
        return RedirectResponse(url("/login?next=/ops"), status_code=303)
    if d.get("u") != settings.MASTER_UID:
        return RedirectResponse(url("/login?next=/ops"), status_code=303)
    acc = await upsert_account(db, d["u"], d.get("e") or "")
    acc.is_operator = True
    await db.commit()
    request.session.clear()
    request.session["aid"] = acc.id
    return RedirectResponse(url(_safe_next(d.get("n")) or "/ops"), status_code=303)


def _safe_next(v) -> str:
    """운영 화면 안쪽 주소만 허용 (/ops/...)"""
    v = str(v or "")
    return v if v.startswith("/ops/") and "//" not in v and "\\" not in v and len(v) < 200 else ""



# ───────────── 전체 회원 (플마 + 영수증리뷰 + 결제) ─────────────

def _plma_state(f: dict, today: str) -> str:
    from datetime import date
    exp = f.get("expires_at") or ""
    expired = bool(exp) and exp < today
    if f.get("status") == "suspended" or (f.get("active") is False and not expired):
        return "stop"
    if expired:
        return "exp"
    if exp:
        try:
            if (date.fromisoformat(exp) - date.fromisoformat(today)).days <= 7:
                return "soon"
        except ValueError:
            pass
    return "ok"


async def _plma_users() -> list[dict]:
    """플마 회원 (Firestore users) — 관리 키로 읽기"""
    token = await firebase.master_access_token()
    out, page = [], None
    base = FS.format(p=settings.FIREBASE_PROJECT_ID)
    async with httpx.AsyncClient(timeout=30) as c:
        while True:
            r = await c.get(f"{base}/users?pageSize=300" + (f"&pageToken={page}" if page else ""),
                            headers={"Authorization": f"Bearer {token}"})
            data = r.json()
            for d in data.get("documents", []):
                f = {k: next(iter(v.values()), None) for k, v in d.get("fields", {}).items() if isinstance(v, dict) and v}
                f["uid"] = d["name"].rsplit("/", 1)[-1]
                out.append(f)
            page = data.get("nextPageToken")
            if not page:
                return out


@router.get("/api/v1/master/customers")
async def customers(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        await _master(request)
    except HTTPException as e:
        return _err(request, e)
    from app.models import Plan, Store
    from app.web import KST
    now = now_utc()
    today = now.astimezone(KST).strftime("%Y-%m-%d")
    people: dict = {}

    def person(email: str, fallback: str) -> dict:
        key = (email or "").strip().lower() or fallback
        return people.setdefault(key, {"email": (email or "").strip().lower(), "name": "", "phone": "", "company": "",
                                       "plma": None, "plma_license": None, "rr": [], "account_id": None,
                                       "paid_total": 0, "plans": []})

    def fill(p: dict, **kv):
        for k, v in kv.items():
            if v and not p.get(k):
                p[k] = v

    products = {x.id: x for x in (await db.execute(select(Product))).scalars()}
    plans = {x.id: x for x in (await db.execute(select(Plan))).scalars()}
    stores = {x.id: x for x in (await db.execute(select(Store))).scalars()}
    paid = dict((await db.execute(select(Order.account_id, func.sum(Order.amount)).where(
        Order.status == OrderStatus.PAID).group_by(Order.account_id))).all())
    linked_review_ids = {s.review_store_id for s in stores.values() if s.review_store_id}

    # 1) 통합 계정 (이용권·결제)
    by_acc = {}
    for a in (await db.execute(select(Account))).scalars():
        if a.firebase_uid == settings.MASTER_UID or a.is_operator:
            continue
        p = person(a.email, f"acc{a.id}")
        p["account_id"] = a.id
        p["paid_total"] = int(paid.get(a.id) or 0)
        fill(p, name=a.name, phone=a.phone, company=a.company)
        by_acc[a.id] = p
    for l in (await db.execute(select(License))).scalars():
        p = by_acc.get(l.account_id)
        prod = products.get(l.product_id)
        if not p or not prod:
            continue
        plan = plans.get(l.plan_id)
        kind = plan.kind.value if plan else "free"
        st = licensing.state(l, now)
        exp = l.expires_at.astimezone(KST).strftime("%Y-%m-%d") if l.expires_at else ""
        if kind != "free" and plan:
            p["plans"].append(plan.name)
        if prod.code == "receipt_review":
            s = stores.get(l.store_id)
            p["rr"].append({"store": s.name if s else "", "state": st, "expires_at": exp, "plan": plan.name if plan else "",
                            "review_store_id": s.review_store_id if s else None, "source": "account"})
        elif prod.code == "plma":
            p["plma_license"] = {"state": st, "expires_at": exp, "plan": plan.name if plan else ""}

    # 2) 플마 회원 (Firestore)
    plma_ok = firebase.master_sa_available()
    if plma_ok:
        try:
            for f in await _plma_users():
                if f["uid"] == settings.MASTER_UID:
                    continue
                p = person(f.get("email", ""), "plma" + f["uid"])
                fill(p, name=f.get("name"), phone=f.get("phone"), company=f.get("company"))
                p["plma"] = {"uid": f["uid"], "state": _plma_state(f, today), "expires_at": f.get("expires_at") or "",
                             "pc": bool(f.get("device_id"))}
        except Exception:
            plma_ok = False

    # 3) 영수증리뷰 매장 (통합 계정으로 아직 안 옮긴 예전 매장 계정 포함)
    review_ok = True
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{settings.REVIEW_API_URL}/internal/ops-stores",
                            headers={"X-Internal-Secret": settings.INTERNAL_SECRET})
        pos = {}
        for s in r.json().get("stores", []):
            pos[s["id"]] = s["pos"]
            if s["id"] in linked_review_ids:
                continue
            login = s.get("login") or ""
            p = person(login if "@" in login else "", "store" + str(s["id"]))
            fill(p, company=s["name"])
            p["rr"].append({"store": s["name"], "state": "active" if s["active"] else "suspended", "expires_at": "",
                            "plan": "", "review_store_id": s["id"], "source": "legacy", "login": login})
        for p in people.values():
            for x in p["rr"]:
                if x.get("review_store_id") in pos:
                    x["pos"] = pos[x["review_store_id"]]
    except Exception:
        review_ok = False

    rows = sorted(people.values(), key=lambda p: (p["company"] or p["name"] or p["email"]))
    return _json(request, {"ok": True, "rows": rows, "plma_ok": plma_ok, "review_ok": review_ok})


# ───────────── 매장 목록 (포스 프로그램 실시간 사용 여부 + 매장별 핵심 데이터) ─────────────

async def _review_get(path: str):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{settings.REVIEW_API_URL}/internal/{path}",
                        headers={"X-Internal-Secret": settings.INTERNAL_SECRET})
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="매장을 찾을 수 없습니다")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="영수증리뷰 서버에서 정보를 받지 못했습니다")
    return r.json()


async def _owners(db: AsyncSession) -> dict:
    """영수증 매장 번호 → 점주(통합 계정)·이용권"""
    from app.models import Plan, Store
    from app.web import KST
    now = now_utc()
    prod = (await db.execute(select(Product).where(Product.code == "receipt_review"))).scalar_one_or_none()
    plans = {x.id: x for x in (await db.execute(select(Plan))).scalars()}
    lic_by_store = {}
    if prod:
        for l in (await db.execute(select(License).where(License.product_id == prod.id))).scalars():
            if l.store_id:
                lic_by_store[l.store_id] = l
    out = {}
    for st in (await db.execute(select(Store).where(Store.review_store_id.isnot(None)))).scalars():
        acc = await db.get(Account, st.account_id)
        l = lic_by_store.get(st.id)
        plan = plans.get(l.plan_id) if l else None
        out[st.review_store_id] = {
            "account_id": acc.id if acc else None,
            "name": acc.name if acc else "", "email": acc.email if acc else "", "phone": acc.phone if acc else "",
            "last_login_at": acc.last_login_at.astimezone(KST).isoformat(timespec="seconds") if acc and acc.last_login_at else None,
            "address": st.address or "",
            "license": {"state": licensing.state(l, now), "plan": plan.name if plan else "",
                        "expires_at": l.expires_at.astimezone(KST).strftime("%Y-%m-%d") if l.expires_at else "",
                        "days_left": licensing.days_left(l, now), "autopay": bool(l.autopay),
                        "device_name": l.device_name or "", "license_id": l.id} if l else None,
        }
    return out


@router.get("/api/v1/master/stores")
async def master_stores(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        await _master(request)
        data = await _review_get("master-stores")
    except HTTPException as e:
        return _err(request, e)
    owners = await _owners(db)
    for s in data.get("stores", []):
        s["owner"] = owners.get(s["id"])
    return _json(request, {"ok": True, **data})


@router.get("/api/v1/master/stores/{store_id}")
async def master_store(store_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        await _master(request)
        data = await _review_get(f"master-stores/{int(store_id)}")
    except HTTPException as e:
        return _err(request, e)
    data["owner"] = (await _owners(db)).get(store_id)
    return _json(request, {"ok": True, **data})
