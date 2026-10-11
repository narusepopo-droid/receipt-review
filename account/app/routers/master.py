"""
마스터(광고토대왕) 전용 API — 플마 관리자 페이지(placemaster.co.kr/admin.html)가 호출

인증: 마스터의 Firebase 로그인 토큰 (Authorization: Bearer <idToken>), UID 가 MASTER_UID 인 경우만
- POST /api/v1/master/plma/delete     플마 회원 완전 삭제 (로그인 계정 + 회원 정보 + 분석 기록)
- POST /api/v1/master/plma/password   플마 회원 비밀번호 직접 변경 (마스터 화면에도 기록)
- GET  /api/v1/master/summary         영수증리뷰·이용권·결제 현황 숫자
- POST /api/v1/master/sso             통합 계정 운영 화면 / 영수증리뷰 운영 화면 바로 열기 (1분짜리 주소)
- GET  /ops/sso?t=                    통합 계정 운영 화면 자동 로그인
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
    acct = settings.BASE_URL.rstrip("/") + "/ops/sso?t=" + _sso_signer().dumps(
        {"u": info["uid"], "e": info.get("email", "")})
    review = settings.REVIEW_PUBLIC_URL.rstrip("/") + "/ops/sso?t=" + URLSafeTimedSerializer(
        settings.INTERNAL_SECRET, salt="master-review-ops").dumps({"u": info["uid"]})
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
    return RedirectResponse(url("/ops"), status_code=303)
