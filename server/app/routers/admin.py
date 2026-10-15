"""
점주 관리자 웹 라우터 - 실제 DB 연동
"""
from datetime import datetime, date, timedelta, timezone
from typing import Optional
import secrets
import hashlib
import io
import zipfile

from fastapi import APIRouter, Request, Response, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Store, StoreSettings, Receipt, ReviewSession, Customer, StoreCustomer
from app.models.receipt import ReceiptStatus
from app.models.session import SessionStatus

templates = Jinja2Templates(directory="app/templates")
templates.env.finalize = lambda v: "" if v is None else v   # 빈 값은 "None" 대신 빈칸


def _kst(dt) -> str:
    """화면 표시용 한국 시간 (DB 는 UTC)"""
    from datetime import timezone as _tz, timedelta as _td
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    return dt.astimezone(_tz(_td(hours=9))).strftime("%m-%d %H:%M")


templates.env.filters["kst"] = _kst

router = APIRouter(prefix="/admin", tags=["admin"])


# ============ Models ============

class PhrasesUpdate(BaseModel):
    keywords: list
    signature_menus: list
    templates: list = []
    text_min_len: int
    text_max_len: int


class SettingsUpdate(BaseModel):
    naver_review_url: Optional[str] = None
    benefit_text: Optional[str] = None
    staff_pin: Optional[str] = None
    pin_required: Optional[bool] = None      # 혜택 지급 때 직원 PIN 사용 (기본: 안 씀)
    primary_color: Optional[str] = None
    paper_width: Optional[int] = None
    assignment_policy: Optional[str] = None
    business_day_cutoff: Optional[str] = None
    hourly_assign_limit: Optional[int] = None
    daily_assign_limit: Optional[int] = None
    new_password: Optional[str] = None


# ============ Session Management ============

async def get_current_store(request: Request, db: AsyncSession):
    """세션에서 현재 로그인된 매장 정보를 가져옵니다."""
    store_id = request.session.get("store_id")
    if not store_id:
        return None

    result = await db.execute(
        select(Store).where(Store.id == store_id)
    )
    store = result.scalar_one_or_none()

    if store:
        # settings도 함께 조회
        settings_result = await db.execute(
            select(StoreSettings).where(StoreSettings.store_id == store_id)
        )
        settings = settings_result.scalar_one_or_none()
        return {"store": store, "settings": settings}

    return None


# ============ Auth Routes ============

@router.get("/login", response_class=HTMLResponse, name="admin_login")
async def login_page(request: Request, error: Optional[str] = None):
    # 통합 계정 로그인으로 (이미 로그인돼 있으면 다시 입력 없이 바로 매장 관리로). 예전 매장 아이디 화면은 ?form=1
    from app.services import account_link
    if not error and request.query_params.get("form") != "1" and account_link.enabled():
        return RedirectResponse(url="/account/my/review-admin", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="admin/login.html",
        context={"error": error}
    )


@router.post("/login", name="admin_login_post")
async def login(
    request: Request,
    login_id: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    from app.security import login_limiter, client_ip
    key = login_limiter.key("admin", client_ip(request), login_id)
    left = login_limiter.remaining_lock(key)
    if left:
        return templates.TemplateResponse(request=request, name="admin/login.html",
                                          context={"error": f"로그인 시도가 너무 많습니다. {left // 60 + 1}분 후 다시 시도하세요."})

    # 통합 계정 서버 (꺼져 있으면 예전 방식)
    from app.services import account_link
    from app.config import settings as _cfg
    if account_link.enabled():
        res = await account_link.owner_login(login_id.strip(), password)
        if res is not None and res.get("ok"):
            login_limiter.success(key)
            usable = [s_ for s_ in res.get("stores", []) if s_.get("usable")]
            if not usable:
                msg = ("이용 중인 영수증리뷰 매장이 없습니다. 마이페이지에서 결제·승인 상태를 확인해 주세요."
                       if res.get("stores") else "영수증리뷰 매장이 없습니다. 마이페이지에서 매장을 추가해 주세요.")
                return templates.TemplateResponse(request=request, name="admin/login.html",
                                                  context={"error": msg, "account_url": _cfg.ACCOUNT_WEB_URL})
            ids = []
            try:
                for s_ in usable:
                    st = await account_link.ensure_review_store(db, s_, login_id)
                    ids.append(st.id)
            except account_link.LinkError as e:
                return templates.TemplateResponse(request=request, name="admin/login.html",
                                                  context={"error": str(e), "account_url": _cfg.ACCOUNT_WEB_URL})
            request.session.clear()
            request.session["owner_store_ids"] = ids
            request.session["store_id"] = ids[0]
            if len(ids) > 1:
                return RedirectResponse(url="/admin/choose-store", status_code=302)
            return RedirectResponse(url="/admin/dashboard", status_code=302)

    # DB에서 매장 조회
    result = await db.execute(
        select(Store).where(Store.admin_login_id == login_id)
    )
    store = result.scalar_one_or_none()

    if store and store.verify_password(password):
        if not await account_link.license_usable(store.id):
            return templates.TemplateResponse(request=request, name="admin/login.html",
                                              context={"error": "이용 기간이 끝났습니다. 마이페이지에서 연장해 주세요."})
        login_limiter.success(key)
        request.session["store_id"] = store.id
        return RedirectResponse(url="/admin/dashboard", status_code=302)
    login_limiter.fail(key)

    return templates.TemplateResponse(
        request=request,
        name="admin/login.html",
        context={"error": "아이디 또는 비밀번호가 올바르지 않습니다."}
    )


@router.get("/sso", name="admin_sso")
async def sso(request: Request, t: str = "", db: AsyncSession = Depends(get_db)):
    """계정 마이페이지 [매장 관리] → 다시 로그인 없이 점주 관리 화면 (1분짜리 서명 토큰)"""
    from itsdangerous import BadSignature, URLSafeTimedSerializer
    from app.config import settings as _cfg
    from app.services import account_link
    if not _cfg.INTERNAL_SECRET:
        return RedirectResponse(url="/admin/login", status_code=302)
    try:
        data = URLSafeTimedSerializer(_cfg.INTERNAL_SECRET, salt="review-sso").loads(t, max_age=60)
    except BadSignature:
        return templates.TemplateResponse(request=request, name="admin/login.html",
                                          context={"error": "바로가기 링크가 만료되었습니다. 마이페이지에서 다시 눌러 주세요."})
    ids, pick = [], None
    for s_ in data.get("stores", []):
        try:
            st = await account_link.ensure_review_store(db, s_, data.get("email", ""))
        except account_link.LinkError as e:
            return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": str(e)})
        ids.append(st.id)
        if s_["id"] == data.get("pick"):
            pick = st.id
    if not ids:
        return RedirectResponse(url="/admin/login", status_code=302)
    request.session.clear()
    request.session["owner_store_ids"] = ids
    request.session["store_id"] = pick or ids[0]
    return RedirectResponse(url="/admin/dashboard", status_code=302)


@router.get("/choose-store", response_class=HTMLResponse, name="admin_choose_store")
async def choose_store(request: Request, db: AsyncSession = Depends(get_db)):
    ids = request.session.get("owner_store_ids") or []
    if not ids:
        return RedirectResponse(url="/admin/login", status_code=302)
    stores = (await db.execute(select(Store).where(Store.id.in_(ids)).order_by(Store.id))).scalars().all()
    return templates.TemplateResponse(request=request, name="admin/choose_store.html",
                                      context={"stores": stores, "current": request.session.get("store_id")})


@router.post("/choose-store", name="admin_choose_store_post")
async def choose_store_post(request: Request, store_id: int = Form(...)):
    if store_id not in (request.session.get("owner_store_ids") or []):
        return RedirectResponse(url="/admin/login", status_code=302)
    request.session["store_id"] = store_id
    return RedirectResponse(url="/admin/dashboard", status_code=302)


@router.get("/logout", name="admin_logout")
async def logout(request: Request):
    request.session.clear()
    from app.services import account_link
    if account_link.enabled():
        # 계정 하나로 쓰므로 통합 계정도 함께 로그아웃 (안 그러면 로그인 화면이 바로 다시 들여보냄)
        return RedirectResponse(url="/account/logout", status_code=302)
    return RedirectResponse(url="/admin/login", status_code=302)


# ============ Dashboard ============

@router.get("/dashboard", response_class=HTMLResponse, name="admin_dashboard")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    store_data = await get_current_store(request, db)
    if not store_data:
        return RedirectResponse(url="/admin/login", status_code=302)

    store = store_data["store"]
    settings = store_data["settings"]

    # 오늘 날짜 (영업일 기준)
    # 한국 시간 기준 (UTC 로 계산하면 '오늘'이 오후 2시에 바뀌던 문제)
    now = datetime.now(timezone(timedelta(hours=9)))
    cutoff = settings.business_day_cutoff if settings else "05:00"
    h, m = map(int, cutoff.split(":"))
    today_start = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if now < today_start:
        today_start -= timedelta(days=1)

    # 어제 시작
    yesterday_start = today_start - timedelta(days=1)

    # 오늘 세션 수
    today_sessions_result = await db.execute(
        select(func.count(ReviewSession.id)).where(
            ReviewSession.store_id == store.id,
            ReviewSession.started_at >= today_start
        )
    )
    today_sessions = today_sessions_result.scalar() or 0

    # 어제 세션 수 (비교용)
    yesterday_sessions_result = await db.execute(
        select(func.count(ReviewSession.id)).where(
            ReviewSession.store_id == store.id,
            ReviewSession.started_at >= yesterday_start,
            ReviewSession.started_at < today_start
        )
    )
    yesterday_sessions = yesterday_sessions_result.scalar() or 0
    sessions_change = today_sessions - yesterday_sessions

    # 사용 가능한 영수증 수
    available_result = await db.execute(
        select(func.count(Receipt.id)).where(
            Receipt.store_id == store.id,
            Receipt.status == ReceiptStatus.AVAILABLE
        )
    )
    available_receipts = available_result.scalar() or 0

    # 오늘 완료된 리뷰 수
    completed_result = await db.execute(
        select(func.count(ReviewSession.id)).where(
            ReviewSession.store_id == store.id,
            ReviewSession.completed_at >= today_start
        )
    )
    completed = completed_result.scalar() or 0

    # 혜택 지급 수
    benefits_result = await db.execute(
        select(func.count(ReviewSession.id)).where(
            ReviewSession.store_id == store.id,
            ReviewSession.benefit_given_at >= today_start
        )
    )
    benefits_given = benefits_result.scalar() or 0
    # PIN 을 안 쓰는 매장(기본)은 '완료 화면 확인 = 지급' 이라 리뷰 완료 수가 곧 지급 수 (혜택 지급 기록 화면과 같게)
    from app.models.options import pin_required as _pin_required
    pin_on = await _pin_required(db, store.id)
    if not pin_on:
        benefits_given = completed

    # 단계별 통계
    step_stats = {}
    for status_name, status_val in [
        ("phone", SessionStatus.STARTED),
        ("keyword", SessionStatus.STARTED),
        ("assign", SessionStatus.ASSIGNED),
        ("download", SessionStatus.DOWNLOADED),
        ("redirect", SessionStatus.REDIRECTED),
        ("complete", SessionStatus.COMPLETED),
        ("benefit", SessionStatus.BENEFIT_GIVEN)
    ]:
        if status_name in ["phone", "keyword"]:
            # started 이상 = phone/keyword 단계 도달
            result = await db.execute(
                select(func.count(ReviewSession.id)).where(
                    ReviewSession.store_id == store.id,
                    ReviewSession.started_at >= today_start
                )
            )
        else:
            result = await db.execute(
                select(func.count(ReviewSession.id)).where(
                    ReviewSession.store_id == store.id,
                    ReviewSession.started_at >= today_start,
                    ReviewSession.status >= status_val
                )
            )
        step_stats[f"step_{status_name}"] = result.scalar() or 0
    if not pin_on:
        step_stats["step_benefit"] = step_stats["step_complete"]

    # 최근 활동
    recent_result = await db.execute(
        select(ReviewSession, Receipt, Customer)
        .outerjoin(Receipt, ReviewSession.receipt_id == Receipt.id)
        .outerjoin(Customer, ReviewSession.customer_id == Customer.id)
        .where(ReviewSession.store_id == store.id)
        .order_by(ReviewSession.started_at.desc())
        .limit(10)
    )

    recent_activities = []
    for session, receipt, customer in recent_result.fetchall():
        phone_masked = "010-****-****"
        if customer and customer.phone_last4:
            phone_masked = f"010-****-{customer.phone_last4}"

        status_class = "secondary"
        status_text = "시작"
        if session.status == SessionStatus.BENEFIT_GIVEN:
            status_class = "success"
            status_text = "혜택지급"
        elif session.status == SessionStatus.COMPLETED:
            status_class = "info"
            status_text = "리뷰완료"
        elif session.status >= SessionStatus.ASSIGNED:
            status_class = "warning"
            status_text = "진행중"

        recent_activities.append({
            "time": session.started_at.strftime("%H:%M") if session.started_at else "",
            "phone_masked": phone_masked,
            "amount": receipt.amount if receipt else 0,
            "status_class": status_class,
            "status_text": status_text
        })

    # 에이전트 상태
    from app.models import Agent
    agent_result = await db.execute(
        select(Agent).where(Agent.store_id == store.id).order_by(Agent.last_heartbeat_at.desc())
    )
    agent = agent_result.scalars().first()

    agent_online = False
    last_heartbeat = "연결 안됨"
    agent_version = "-"
    capture_mode = "-"
    queue_length = 0

    if agent:
        hb = agent.last_heartbeat_at
        if hb is not None and hb.tzinfo is None:
            hb = hb.replace(tzinfo=timezone.utc)
        time_diff = datetime.now(timezone.utc) - hb if hb else timedelta(hours=999)
        agent_online = time_diff < timedelta(minutes=5)

        if agent.last_heartbeat_at:
            if time_diff < timedelta(minutes=1):
                last_heartbeat = "방금 전"
            elif time_diff < timedelta(hours=1):
                last_heartbeat = f"{int(time_diff.total_seconds() // 60)}분 전"
            else:
                last_heartbeat = f"{int(time_diff.total_seconds() // 3600)}시간 전"

        agent_version = agent.version or "-"
        capture_mode = agent.capture_mode or "-"
        queue_length = agent.queue_length or 0

    # 오늘 수신된 영수증 수
    today_receipts_result = await db.execute(
        select(func.count(Receipt.id)).where(
            Receipt.store_id == store.id,
            Receipt.created_at >= today_start
        )
    )
    today_receipts = today_receipts_result.scalar() or 0

    from app.services.otp import get_options
    from app.services.review_check import verified_count
    review_check_on = (await get_options(db, store.id)).review_check
    verified_7d = await verified_count(db, store.id) if review_check_on else None

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "store": {
                "id": store.id,
                "name": store.name,
                "biz_no": store.biz_no,
                "store_code": store.store_code
            },
            "active_menu": "dashboard",
            "today": date.today(),
            "stats": {
                "today_sessions": today_sessions,
                "sessions_change": sessions_change,
                "available_receipts": available_receipts,
                "completed": completed,
                "benefits_given": benefits_given,
                **step_stats
            },
            "agent_online": agent_online,
            "last_heartbeat": last_heartbeat,
            "agent_version": agent_version,
            "capture_mode": capture_mode,
            "queue_length": queue_length,
            "today_receipts": today_receipts,
            "verified_7d": verified_7d,
            "recent_activities": recent_activities
        }
    )


# ============ Customers ============

@router.get("/customers", response_class=HTMLResponse, name="admin_customers")
async def customers_page(request: Request, page: int = 1, db: AsyncSession = Depends(get_db)):
    store_data = await get_current_store(request, db)
    if not store_data:
        return RedirectResponse(url="/admin/login", status_code=302)

    store = store_data["store"]
    per_page = 20
    offset = (page - 1) * per_page

    # 고객 목록 조회
    customers_result = await db.execute(
        select(StoreCustomer, Customer)
        .join(Customer, StoreCustomer.customer_id == Customer.id)
        .where(StoreCustomer.store_id == store.id)
        .order_by(StoreCustomer.last_visit_at.desc())
        .offset(offset)
        .limit(per_page)
    )

    customers = []
    for sc, customer in customers_result.fetchall():
        phone_masked = "010-****-****"
        if customer.phone_last4:
            phone_masked = f"010-****-{customer.phone_last4}"

        customers.append({
            "id": customer.id,
            "phone_masked": phone_masked,
            "first_visit_at": sc.first_visit_at,
            "last_visit_at": sc.last_visit_at,
            "visit_count": sc.visit_count,
            "marketing_opt_in": sc.marketing_opt_in,
            "total_amount": sc.total_amount or 0,
            "review_count": sc.review_count or 0
        })

    # 통계
    total_result = await db.execute(
        select(func.count(StoreCustomer.customer_id)).where(
            StoreCustomer.store_id == store.id
        )
    )
    total = total_result.scalar() or 0

    opted_in_result = await db.execute(
        select(func.count(StoreCustomer.customer_id)).where(
            StoreCustomer.store_id == store.id,
            StoreCustomer.marketing_opt_in == True
        )
    )
    opted_in = opted_in_result.scalar() or 0

    returning_result = await db.execute(
        select(func.count(StoreCustomer.customer_id)).where(
            StoreCustomer.store_id == store.id,
            StoreCustomer.visit_count > 1
        )
    )
    returning = returning_result.scalar() or 0

    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_this_month_result = await db.execute(
        select(func.count(StoreCustomer.customer_id)).where(
            StoreCustomer.store_id == store.id,
            StoreCustomer.first_visit_at >= month_start
        )
    )
    new_this_month = new_this_month_result.scalar() or 0

    total_pages = (total + per_page - 1) // per_page

    return templates.TemplateResponse(
        request=request,
        name="admin/customers.html",
        context={
            "store": {"id": store.id, "name": store.name},
            "active_menu": "customers",
            "customers": customers,
            "stats": {
                "total": total,
                "opted_in": opted_in,
                "returning": returning,
                "new_this_month": new_this_month
            },
            "current_page": page,
            "total_pages": total_pages
        }
    )


# ============ Receipts ============

@router.get("/receipts", response_class=HTMLResponse, name="admin_receipts")
async def receipts_page(request: Request, page: int = 1, status: str = "all", db: AsyncSession = Depends(get_db)):
    """영수증 목록 - 상태별 조회"""
    store_data = await get_current_store(request, db)
    if not store_data:
        return RedirectResponse(url="/admin/login", status_code=302)

    store = store_data["store"]
    per_page = 30
    offset = (page - 1) * per_page

    # 필터 조건
    conditions = [Receipt.store_id == store.id]
    if status == "available":
        conditions.append(Receipt.status == ReceiptStatus.AVAILABLE)
    elif status == "assigned":
        conditions.append(Receipt.status == ReceiptStatus.ASSIGNED)
    elif status == "disposed":
        conditions.append(Receipt.status == ReceiptStatus.DISPOSED)

    # 영수증 목록
    receipts_result = await db.execute(
        select(Receipt)
        .where(and_(*conditions))
        .order_by(Receipt.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    receipts = receipts_result.scalars().all()

    # 상태별 카운트
    available_count = (await db.execute(
        select(func.count(Receipt.id)).where(
            Receipt.store_id == store.id,
            Receipt.status == ReceiptStatus.AVAILABLE
        )
    )).scalar() or 0

    assigned_count = (await db.execute(
        select(func.count(Receipt.id)).where(
            Receipt.store_id == store.id,
            Receipt.status == ReceiptStatus.ASSIGNED
        )
    )).scalar() or 0

    disposed_count = (await db.execute(
        select(func.count(Receipt.id)).where(
            Receipt.store_id == store.id,
            Receipt.status == ReceiptStatus.DISPOSED
        )
    )).scalar() or 0

    total = available_count + assigned_count + disposed_count
    total_pages = (total + per_page - 1) // per_page if status == "all" else 1

    return templates.TemplateResponse(
        request=request,
        name="admin/receipts.html",
        context={
            "store": {"id": store.id, "name": store.name},
            "active_menu": "receipts",
            "receipts": receipts,
            "status_filter": status,
            "counts": {
                "all": total,
                "available": available_count,
                "assigned": assigned_count,
                "disposed": disposed_count
            },
            "current_page": page,
            "total_pages": total_pages
        }
    )


# ============ Phrases ============

@router.get("/phrases", response_class=HTMLResponse, name="admin_phrases")
async def phrases_page(request: Request, db: AsyncSession = Depends(get_db)):
    store_data = await get_current_store(request, db)
    if not store_data:
        return RedirectResponse(url="/admin/login", status_code=302)

    store = store_data["store"]
    settings = store_data["settings"]

    from app.review.phrase_bank import DEFAULT_KEYWORDS, BANK
    keywords = settings.keywords if settings and settings.keywords else DEFAULT_KEYWORDS

    signature_menus = settings.signature_menus if settings and settings.signature_menus else []

    return templates.TemplateResponse(
        request=request,
        name="admin/phrases.html",
        context={
            "store": {"id": store.id, "name": store.name},
            "active_menu": "phrases",
            "keywords": keywords,
            "signature_menus": signature_menus,
            "bank_counts": {k: len(v) for k, v in BANK.items()},
            "text_min_len": settings.text_min_len if settings else 30,
            "text_max_len": settings.text_max_len if settings else 150
        }
    )


@router.post("/phrases/preview", name="admin_preview_phrases")
async def preview_phrases(request: Request, data: PhrasesUpdate, db: AsyncSession = Depends(get_db)):
    """저장 전 화면 값으로 실제 생성 방식(문장 묶음 조합)을 5번 돌려 미리보기 (사용 기록 없음)"""
    store_data = await get_current_store(request, db)
    if not store_data:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    from app.review.text_generator import TextGenerator
    from app.review.phrase_bank import MIN_KEYWORDS
    import random as _random
    gen = TextGenerator(db)
    store_id = store_data["store"].id
    custom = {k["label"]: [p for p in k.get("phrases", []) if p]
              for k in data.keywords if isinstance(k, dict) and k.get("label") and k.get("phrases")}
    labels = [k["label"] for k in data.keywords if isinstance(k, dict) and k.get("label")]
    menus = [m for m in data.signature_menus if m]
    texts = []
    for _ in range(5):
        n = min(len(labels), _random.randint(MIN_KEYWORDS, MIN_KEYWORDS + 2))
        chosen = _random.sample(labels, k=n) if labels else []
        text, _picked = await gen.compose(store_id, chosen, menus, custom, data.text_max_len, mark=False)
        texts.append({"text": text, "len": len(text),
                      "ok": data.text_min_len <= len(text) <= data.text_max_len, "keywords": chosen})
    return JSONResponse({"texts": texts})


@router.post("/phrases/save", name="admin_save_phrases")
async def save_phrases(request: Request, data: PhrasesUpdate, db: AsyncSession = Depends(get_db)):
    store_data = await get_current_store(request, db)
    if not store_data:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    store = store_data["store"]

    # settings 조회 또는 생성
    result = await db.execute(
        select(StoreSettings).where(StoreSettings.store_id == store.id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = StoreSettings(store_id=store.id)
        db.add(settings)

    settings.keywords = data.keywords
    settings.signature_menus = data.signature_menus
    settings.templates = []   # 템플릿 방식은 사용하지 않음 (문장 묶음 조합)
    settings.text_min_len = data.text_min_len
    settings.text_max_len = data.text_max_len

    await db.commit()
    return JSONResponse({"success": True})


# ============ Settings ============

@router.get("/settings", response_class=HTMLResponse, name="admin_settings")
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    store_data = await get_current_store(request, db)
    if not store_data:
        return RedirectResponse(url="/admin/login", status_code=302)

    store = store_data["store"]
    settings = store_data["settings"] or {}
    from app.services.otp import get_options
    from app.models.options import pin_required
    opts = await get_options(db, store.id)

    return templates.TemplateResponse(
        request=request,
        name="admin/settings.html",
        context={
            "store": {"id": store.id, "name": store.name, "naver_review_url": store.review_url, "staff_pin": store.staff_pin},
            "pin_required": await pin_required(db, store.id),
            "active_menu": "settings",
            "options": {"phone_verify": opts.phone_verify,
                        "review_check": opts.review_check, "naver_place_id": opts.naver_place_id or ""},
            "settings": {
                "benefit_text": settings.benefit_text if settings else "",
                "primary_color": settings.primary_color if settings else "#03C75A",
                "assignment_policy": settings.assignment_policy if settings else "latest_same_day",
                "business_day_cutoff": settings.business_day_cutoff if settings else "05:00",
                "hourly_assign_limit": settings.hourly_assign_limit if settings else 50,
                "daily_assign_limit": settings.daily_assign_limit if settings else 200
            }
        }
    )


@router.post("/settings/save", name="admin_save_settings")
async def save_settings(request: Request, data: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    store_data = await get_current_store(request, db)
    if not store_data:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    store = store_data["store"]

    # Store 업데이트
    if data.naver_review_url:
        store.naver_review_url = data.naver_review_url
    pin = (data.staff_pin or "").strip()
    if pin and not (len(pin) == 4 and pin.isdigit()):
        return JSONResponse({"success": False, "error": "직원 PIN은 숫자 4자리로 정해 주세요"}, status_code=400)
    if pin:
        store.staff_pin = pin
    if data.pin_required is not None:
        from app.models.options import BenefitOption
        if data.pin_required and not store.staff_pin:
            return JSONResponse({"success": False, "error": "PIN 확인을 쓰려면 직원 PIN 4자리를 정해 주세요"}, status_code=400)
        o = (await db.execute(select(BenefitOption).where(BenefitOption.store_id == store.id))).scalar_one_or_none()
        if not o:
            o = BenefitOption(store_id=store.id)
            db.add(o)
        o.pin_required = bool(data.pin_required)
    if data.new_password:
        store.set_password(data.new_password)

    # Settings 업데이트
    result = await db.execute(
        select(StoreSettings).where(StoreSettings.store_id == store.id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = StoreSettings(store_id=store.id)
        db.add(settings)

    if data.benefit_text:
        settings.benefit_text = data.benefit_text
    if data.primary_color:
        settings.primary_color = data.primary_color
    if data.assignment_policy:
        settings.assignment_policy = data.assignment_policy
    if data.business_day_cutoff:
        settings.business_day_cutoff = data.business_day_cutoff
    if data.hourly_assign_limit:
        settings.hourly_assign_limit = data.hourly_assign_limit
    if data.daily_assign_limit:
        settings.daily_assign_limit = data.daily_assign_limit

    await db.commit()
    return JSONResponse({"success": True})


# ============ 혜택 지급 기록 ============

_KST = timezone(timedelta(hours=9))


@router.get("/benefits", response_class=HTMLResponse, name="admin_benefits")
async def benefits_page(request: Request, days: int = 7, page: int = 1, db: AsyncSession = Depends(get_db)):
    """리뷰 완료·혜택 지급 기록 (번호는 가려서)"""
    store_data = await get_current_store(request, db)
    if not store_data:
        return RedirectResponse(url="/admin/login", status_code=302)
    from app.models.options import pin_required
    store = store_data["store"]
    days = days if days in (1, 7, 30, 90) else 7
    page = max(page, 1)
    per_page = 50
    today0 = datetime.now(_KST).replace(hour=0, minute=0, second=0, microsecond=0)
    since = (today0 - timedelta(days=days - 1)).astimezone(timezone.utc)
    done = and_(ReviewSession.store_id == store.id, ReviewSession.completed_at.isnot(None),
                ReviewSession.completed_at >= since)

    total = (await db.execute(select(func.count()).select_from(ReviewSession).where(done))).scalar() or 0
    given = (await db.execute(select(func.count()).select_from(ReviewSession).where(
        done, ReviewSession.benefit_given_at.isnot(None)))).scalar() or 0
    today_cnt = (await db.execute(select(func.count()).select_from(ReviewSession).where(
        done, ReviewSession.completed_at >= today0.astimezone(timezone.utc)))).scalar() or 0
    rows = (await db.execute(
        select(ReviewSession, Customer).join(Customer, ReviewSession.customer_id == Customer.id)
        .where(done).order_by(ReviewSession.completed_at.desc())
        .offset((page - 1) * per_page).limit(per_page))).all()

    def kst(t):
        if not t:
            return ""
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(_KST).strftime("%m-%d %H:%M")

    records = [{
        "completed_at": kst(s.completed_at),
        "phone_masked": f"010-****-{c.phone_last4}" if c.phone_last4 else "010-****-****",
        "table_no": "" if (s.table_no or "0") == "0" else s.table_no,   # 0 = 매장 공용 QR
        "benefit_given_at": kst(s.benefit_given_at),
    } for s, c in rows]

    return templates.TemplateResponse(
        request=request,
        name="admin/benefits.html",
        context={
            "store": {"id": store.id, "name": store.name},
            "active_menu": "benefits",
            "pin_required": await pin_required(db, store.id),
            "days": days, "records": records,
            "stats": {"total": total, "given": given, "today": today_cnt},
            "current_page": page, "total_pages": max(1, (total + per_page - 1) // per_page),
        }
    )


# ============ Tables ============

SIGN_BASE_URL = "https://review.placemaster.co.kr"
SIGN_DEFAULT_STEPS = ("음식/매장 사진 2장 먼저 촬영\n"
                      "QR 찍고 휴대폰 번호 입력\n"
                      "영수증·리뷰 글 자동 준비 → 네이버로 이동\n"
                      "앨범에서 영수증+사진 첨부\n"
                      "글 붙여넣기 → 등록 완료!")
# 손님이 '일반 네이버 영수증 QR'로 착각하지 않게 맨 위 강조 문구 (점주가 시안 중 고르거나 직접 수정)
SIGN_DEFAULT_HEADLINE = "영수증리뷰 자동완성\n영수증 요청 없이 QR 한 번이면 끝!!"   # 핵심 키워드 '영수증리뷰 자동완성' (요청자 결정)
SIGN_TEMPLATES = ("glass", "neon", "minimal", "luxury")
SIGN_SIZES = ("a6", "a5", "tablet", "square", "custom")


def _sign_defaults(store, settings) -> dict:
    return {
        "template": "glass", "size": "a6", "customW": None, "customH": None, "color": "#03C75A",
        "storeName": store.name,
        "benefit": (settings.benefit_text if settings and settings.benefit_text else "리뷰 작성 시 음료 1잔 서비스"),
        "headline": SIGN_DEFAULT_HEADLINE,
        "steps": SIGN_DEFAULT_STEPS, "logo": None,
        "qrMode": "store", "tableStart": 1, "tableEnd": 10, "tablePrefix": "테이블",
    }


def _clean_design(raw: dict, base: dict) -> dict:
    """점주가 보낸 디자인 값 검사 (모르는 키·이상한 값은 기본값)"""
    import re
    d = dict(base)
    def txt(k, n):
        v = raw.get(k)
        if isinstance(v, str):
            d[k] = v[:n]
    txt("storeName", 40); txt("benefit", 60); txt("steps", 400); txt("tablePrefix", 10); txt("headline", 90)
    if raw.get("template") in SIGN_TEMPLATES:
        d["template"] = raw["template"]
    if raw.get("size") in SIGN_SIZES:
        d["size"] = raw["size"]
    if isinstance(raw.get("color"), str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", raw["color"]):
        d["color"] = raw["color"]
    for k, lo, hi in (("customW", 50, 500), ("customH", 50, 500), ("tableStart", 1, 999), ("tableEnd", 1, 999)):
        try:
            d[k] = max(lo, min(hi, int(raw[k]))) if raw.get(k) not in (None, "") else base[k]
        except (TypeError, ValueError):
            pass
    if d["tableEnd"] < d["tableStart"]:
        d["tableEnd"] = d["tableStart"]
    d["tableEnd"] = min(d["tableEnd"], d["tableStart"] + 99)        # 한 번에 100장까지
    if raw.get("qrMode") in ("store", "table"):
        d["qrMode"] = raw["qrMode"]
    logo = raw.get("logo")
    if logo is None or (isinstance(logo, str) and len(logo) <= 700_000
                        and re.match(r"^data:image/(png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=]+$", logo)):
        d["logo"] = logo
    return d


async def _load_design(db, store, settings) -> dict:
    import json
    from app.models.options import SignDesign
    base = _sign_defaults(store, settings)
    row = await db.get(SignDesign, store.id)
    if not row:
        return base
    try:
        return _clean_design(json.loads(row.data or "{}"), base)
    except ValueError:
        return base


@router.get("/tables", response_class=HTMLResponse, name="admin_tables")
async def tables_page(request: Request, db: AsyncSession = Depends(get_db)):
    """테이블 안내판 편집기 — 템플릿 4종·크기·색·문구·로고, 매장 공용 QR 또는 테이블별 QR"""
    store_data = await get_current_store(request, db)
    if not store_data:
        return RedirectResponse(url="/admin/login", status_code=302)

    store = store_data["store"]
    design = await _load_design(db, store, store_data["settings"])
    return templates.TemplateResponse(
        request=request,
        name="admin/tables.html",
        context={
            "store": {"id": store.id, "name": store.name, "store_code": store.store_code},
            "active_menu": "tables",
            "design": design,
            "qr_base": f"{SIGN_BASE_URL}/t/{store.store_code}/",
        }
    )


@router.post("/tables/design", name="admin_save_sign_design")
async def save_sign_design(request: Request, db: AsyncSession = Depends(get_db)):
    import json
    from app.models.options import SignDesign
    store_data = await get_current_store(request, db)
    if not store_data:
        return JSONResponse({"success": False, "error": "다시 로그인해 주세요"}, status_code=401)
    store = store_data["store"]
    try:
        raw = await request.json()
    except ValueError:
        return JSONResponse({"success": False, "error": "잘못된 요청"}, status_code=400)
    if not isinstance(raw, dict):
        return JSONResponse({"success": False, "error": "잘못된 요청"}, status_code=400)
    design = _clean_design(raw, _sign_defaults(store, store_data["settings"]))
    row = await db.get(SignDesign, store.id)
    if not row:
        row = SignDesign(store_id=store.id)
        db.add(row)
    row.data = json.dumps(design, ensure_ascii=False)
    await db.commit()
    return {"success": True, "design": design}


@router.get("/tables/qr.png", name="admin_sign_qr")
async def sign_qr(request: Request, t: str = "0", db: AsyncSession = Depends(get_db)):
    """이 매장 QR 이미지. t=0 은 매장 공용 QR, 숫자는 테이블 번호"""
    store_data = await get_current_store(request, db)
    if not store_data:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    if not (t.isdigit() and 0 <= int(t) <= 999):
        raise HTTPException(status_code=400, detail="테이블 번호는 숫자로")
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=20, border=2)
    qr.add_data(f"{SIGN_BASE_URL}/t/{store_data['store'].store_code}/{int(t)}")
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")   # 늘리지 않아 인쇄해도 선명
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600"})


@router.get("/tables/download", name="admin_download_tables")
async def download_tables(
    request: Request,
    format: str = "pdf",
    count: int = 10,
    start: int = 1,
    size: str = "A6",
    db: AsyncSession = Depends(get_db)
):
    store_data = await get_current_store(request, db)
    if not store_data:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    store = store_data["store"]
    settings = store_data["settings"]

    from app.services.signage import SignageConfig, generate_signage_pdf, generate_signage_png

    config = SignageConfig(
        store_name=store.name,
        store_code=store.store_code,
        benefit_text=(settings.benefit_text if settings and settings.benefit_text else "리뷰 작성 시 음료 1잔 서비스"),
        table_count=max(1, min(count, 200)),
        size=size if size in ("A5", "A6") else "A6",
        start_no=max(1, start),
    )

    if format == "pdf":
        pdf_bytes = generate_signage_pdf(config)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=tables_{start}-{start+count-1}.pdf"
            }
        )
    else:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for i in range(start, start + count):
                png_bytes = generate_signage_png(config, i)
                zip_file.writestr(f"table_{i}.png", png_bytes)

        zip_buffer.seek(0)
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=tables_{start}-{start+count-1}.zip"
            }
        )



# ============ 홍보 문자 (Phase 8) ============

class SmsRequest(BaseModel):
    body: str
    scheduled_at: Optional[str] = None   # "2026-10-09T14:30" (한국 시간), 없으면 즉시


def _parse_kst(value: Optional[str]):
    from datetime import timezone as _tz, timedelta as _td
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=_tz(_td(hours=9)))


@router.get("/sms", response_class=HTMLResponse, name="admin_sms")
async def sms_page(request: Request, db: AsyncSession = Depends(get_db)):
    store_data = await get_current_store(request, db)
    if not store_data:
        return RedirectResponse(url="/admin/login", status_code=302)
    store = store_data["store"]

    from app.services import sms as sms_service
    from app.models.sms import SmsCampaign
    wallet = await sms_service.get_wallet(db, store.id)
    await db.commit()
    targets = len(await sms_service.opted_in_customers(db, store.id))
    history = (await db.execute(select(SmsCampaign).where(SmsCampaign.store_id == store.id)
                                .order_by(SmsCampaign.created_at.desc()).limit(50))).scalars().all()
    return templates.TemplateResponse(request=request, name="admin/sms.html", context={
        "store": {"id": store.id, "name": store.name}, "active_menu": "sms",
        "balance": wallet.balance, "targets": targets, "history": history,
        "test_mode": sms_service.is_test_mode(),
        "cost_sms": sms_service.unit_cost("SMS"), "cost_lms": sms_service.unit_cost("LMS"),
    })


@router.post("/sms/preview", name="admin_sms_preview")
async def sms_preview(request: Request, data: SmsRequest, db: AsyncSession = Depends(get_db)):
    store_data = await get_current_store(request, db)
    if not store_data:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    from app.services import sms as sms_service
    store = store_data["store"]
    final, msg_type = sms_service.compose(store, data.body or "")
    targets = len(await sms_service.opted_in_customers(db, store.id))
    when = _parse_kst(data.scheduled_at)
    return JSONResponse({
        "final_text": final, "msg_type": msg_type, "bytes": sms_service.text_bytes(final),
        "targets": targets, "cost": sms_service.unit_cost(msg_type) * targets,
        "night_blocked": sms_service.is_night(when or datetime.now(timezone.utc)),
    })


@router.post("/sms/send", name="admin_sms_send")
async def sms_send(request: Request, data: SmsRequest, db: AsyncSession = Depends(get_db)):
    store_data = await get_current_store(request, db)
    if not store_data:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    from app.services import sms as sms_service
    store = store_data["store"]
    try:
        when = _parse_kst(data.scheduled_at)
        campaign = await sms_service.create_campaign(db, store, data.body, when)
        if when is None or when <= datetime.now(timezone.utc):
            await sms_service.send_campaign(db, campaign)
        await db.commit()
    except sms_service.SmsError as e:
        await db.rollback()
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except ValueError:
        await db.rollback()
        return JSONResponse({"success": False, "error": "예약 시각 형식이 올바르지 않습니다"}, status_code=400)
    return JSONResponse({"success": True, "status": campaign.status.value, "test_mode": campaign.test_mode,
                         "success_count": campaign.success_count, "target_count": campaign.target_count})


@router.post("/sms/{campaign_id}/cancel", name="admin_sms_cancel")
async def sms_cancel(request: Request, campaign_id: int, db: AsyncSession = Depends(get_db)):
    store_data = await get_current_store(request, db)
    if not store_data:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    from app.models.sms import SmsCampaign, SmsStatus
    c = (await db.execute(select(SmsCampaign).where(
        SmsCampaign.id == campaign_id, SmsCampaign.store_id == store_data["store"].id))).scalar_one_or_none()
    if not c or c.status != SmsStatus.SCHEDULED:
        return JSONResponse({"success": False, "error": "취소할 수 없는 문자입니다"}, status_code=400)
    c.status = SmsStatus.CANCELLED
    await db.commit()
    return JSONResponse({"success": True})



# ============ 선택 기능 (Phase 9) ============

class OptionsUpdate(BaseModel):
    phone_verify: bool = False
    review_check: bool = False
    naver_place_id: Optional[str] = None


@router.post("/options/save", name="admin_save_options")
async def save_options(request: Request, data: OptionsUpdate, db: AsyncSession = Depends(get_db)):
    store_data = await get_current_store(request, db)
    if not store_data:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    import re as _re
    from app.models.options import StoreOptions
    store = store_data["store"]
    place = None
    if data.naver_place_id:
        m = _re.search(r"(\d{5,15})", data.naver_place_id)   # 플레이스 주소를 붙여넣어도 번호만 추출
        place = m.group(1) if m else None
    if data.review_check and not place:
        return JSONResponse({"success": False, "error": "리뷰 확인을 켜려면 네이버 플레이스 주소(또는 번호)가 필요합니다"}, status_code=400)
    o = (await db.execute(select(StoreOptions).where(StoreOptions.store_id == store.id))).scalar_one_or_none()
    if not o:
        o = StoreOptions(store_id=store.id)
        db.add(o)
    o.phone_verify, o.review_check, o.naver_place_id = data.phone_verify, data.review_check, place
    await db.commit()
    return JSONResponse({"success": True, "naver_place_id": place})
