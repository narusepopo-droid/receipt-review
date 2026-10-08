"""
운영자 웹 라우터 (광고토대왕 전용)
Phase 5: 매장 관리, 에이전트 관리, 통계
"""
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, and_, select
from pydantic import BaseModel

from app.db import get_db
from app.models.store import Store, StoreStatus, StoreSettings, Agent
from app.models.receipt import Receipt, ReceiptStatus, ReceiptClassification
from app.models.session import ReviewSession

KST = timezone(timedelta(hours=9))

router = APIRouter(prefix="/ops", tags=["operations"])

templates = Jinja2Templates(directory="app/templates")


# ============ Pydantic Models ============

class StoreCreate(BaseModel):
    name: str
    biz_no: str
    naver_review_url: str
    paper_width: int = 576
    admin_login_id: str
    admin_password: str
    staff_pin: str


class StoreUpdate(BaseModel):
    name: Optional[str] = None
    biz_no: Optional[str] = None
    naver_review_url: Optional[str] = None
    paper_width: Optional[int] = None
    status: Optional[str] = None
    staff_pin: Optional[str] = None


class ActivationCodeResponse(BaseModel):
    code: str
    expires_at: datetime
    store_id: int


class AgentStatusItem(BaseModel):
    store_id: int
    store_name: str
    agent_id: Optional[int]
    version: Optional[str]
    capture_mode: Optional[str]
    last_heartbeat_at: Optional[datetime]
    last_capture_at: Optional[datetime]
    queue_length: int
    status: str  # "online", "warning", "offline"
    warning_message: Optional[str]


class StoreStats(BaseModel):
    store_id: int
    store_name: str
    total_sessions: int
    completed_sessions: int
    conversion_rate: float
    today_sessions: int
    today_completed: int
    available_receipts: int
    total_customers: int


class InstallerVersion(BaseModel):
    version: str
    filename: str
    sha256: str
    release_date: datetime
    download_count: int


# ============ 운영자 인증 (간단 세션) ============

from app.config import settings as _settings  # noqa: E402
from app.security import login_limiter, client_ip  # noqa: E402
import hmac as _hmac  # noqa: E402


def verify_ops_session(request: Request) -> bool:
    """운영자 세션 확인"""
    return request.session.get("ops_authenticated", False)


def require_ops_auth(request: Request):
    """운영자 인증 필수 의존성"""
    if not verify_ops_session(request):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/ops/login"}
        )


# ============ 로그인 ============

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """운영자 로그인 페이지"""
    return templates.TemplateResponse(
        request=request,
        name="ops/login.html",
        context={
        
        "error": None
    })


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    """운영자 로그인 처리 (5회 실패 시 10분 잠금)"""
    key = login_limiter.key("ops", client_ip(request), username)
    left = login_limiter.remaining_lock(key)
    if left:
        return templates.TemplateResponse(request=request, name="ops/login.html",
                                          context={"error": f"로그인 시도가 너무 많습니다. {left // 60 + 1}분 후 다시 시도하세요."})

    ok_user = _hmac.compare_digest(username, _settings.OPS_USERNAME)
    ok_pass = _hmac.compare_digest(password, _settings.OPS_PASSWORD)
    if ok_user and ok_pass:
        login_limiter.success(key)
        request.session["ops_authenticated"] = True
        return RedirectResponse(url="/ops/dashboard", status_code=303)
    login_limiter.fail(key)

    return templates.TemplateResponse(
        request=request,
        name="ops/login.html",
        context={
        
        "error": "아이디 또는 비밀번호가 올바르지 않습니다."
    })


@router.get("/logout")
async def logout(request: Request):
    """운영자 로그아웃"""
    request.session.clear()
    return RedirectResponse(url="/ops/login", status_code=303)


# ============ 대시보드 ============

def _aware(dt):
    """DB 에서 읽은 시각을 UTC aware 로 (SQLite 는 naive)"""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _kst_day_start() -> datetime:
    now = datetime.now(KST)
    return datetime.combine(now.date(), datetime.min.time(), tzinfo=KST)


def agent_health(agent: Optional[Agent]) -> tuple[str, Optional[str]]:
    """에이전트 상태: online / warning / offline + 경고 문구"""
    if not agent or not agent.last_heartbeat_at:
        return "offline", "연결 기록 없음"
    now = datetime.now(timezone.utc)
    gap = now - _aware(agent.last_heartbeat_at)
    if gap > timedelta(minutes=30):
        return "offline", f"{int(gap.total_seconds() // 60)}분째 연결 끊김"
    warnings = []
    if gap > timedelta(minutes=5):
        warnings.append(f"하트비트 {int(gap.total_seconds() // 60)}분 지연")
    if (agent.queue_length or 0) > 20:
        warnings.append(f"전송 대기 {agent.queue_length}건 (서버 전송 실패)")
    last_cap = _aware(agent.last_capture_at)
    if last_cap is None:
        warnings.append("영수증 수신 0건 (프린터 연결 확인)")
    elif now - last_cap > timedelta(hours=24):
        warnings.append("24시간 동안 영수증 없음")
    return ("warning" if warnings else "online"), (", ".join(warnings) or None)


async def _latest_agents(db: AsyncSession) -> dict:
    """매장별 가장 최근 하트비트 에이전트"""
    rows = (await db.execute(select(Agent))).scalars().all()
    best = {}
    for a in rows:
        cur = best.get(a.store_id)
        if cur is None or (_aware(a.last_heartbeat_at) or datetime.min.replace(tzinfo=timezone.utc)) > \
                (_aware(cur.last_heartbeat_at) or datetime.min.replace(tzinfo=timezone.utc)):
            best[a.store_id] = a
    return best


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """운영자 대시보드"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    stores = (await db.execute(select(Store))).scalars().all()
    agents = await _latest_agents(db)
    health = [agent_health(agents.get(s.id))[0] for s in stores if s.status == StoreStatus.ACTIVE]
    today = _kst_day_start()

    stats = {
        "total_stores": len(stores),
        "active_stores": sum(1 for s in stores if s.status == StoreStatus.ACTIVE),
        "online_agents": sum(1 for h in health if h != "offline"),
        "offline_agents": sum(1 for h in health if h == "offline"),
        "today_sessions": (await db.execute(select(func.count(ReviewSession.id)).where(
            ReviewSession.started_at >= today))).scalar() or 0,
        "today_completed": (await db.execute(select(func.count(ReviewSession.id)).where(
            ReviewSession.started_at >= today, ReviewSession.completed_at.isnot(None)))).scalar() or 0,
        "unclassified_count": (await db.execute(select(func.count(Receipt.id)).where(
            Receipt.classification == ReceiptClassification.UNCLASSIFIED,
            Receipt.status != ReceiptStatus.DISPOSED))).scalar() or 0,
    }

    return templates.TemplateResponse(request=request, name="ops/dashboard.html", context={"stats": stats})


# ============ 매장 관리 ============

@router.get("/stores", response_class=HTMLResponse)
async def stores_list(request: Request, db: AsyncSession = Depends(get_db)):
    """매장 목록"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    agents = await _latest_agents(db)
    rows = (await db.execute(select(Store).order_by(Store.created_at.desc()))).scalars().all()
    stores = [{
        "id": s.id, "name": s.name, "biz_no": s.biz_no, "store_code": s.store_code,
        "status": s.status.value if hasattr(s.status, "value") else s.status,
        "agent_connected": agent_health(agents.get(s.id))[0] != "offline",
        "created_at": s.created_at,
    } for s in rows]

    return templates.TemplateResponse(request=request, name="ops/stores.html", context={"stores": stores})


@router.get("/stores/new", response_class=HTMLResponse)
async def store_new_form(request: Request):
    """매장 등록 폼"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    return templates.TemplateResponse(request=request, name="ops/store_form.html",
                                      context={"store": None, "mode": "create"})


async def _new_store_code(db: AsyncSession) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(20):
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if not (await db.execute(select(Store.id).where(Store.store_code == code))).first():
            return code
    raise HTTPException(status_code=500, detail="매장 코드 생성 실패")


@router.post("/stores/new")
async def store_create(
    request: Request,
    name: str = Form(...),
    biz_no: str = Form(""),
    naver_review_url: str = Form(""),
    paper_width: int = Form(576),
    admin_login_id: str = Form(...),
    admin_password: str = Form(...),
    staff_pin: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    """매장 등록 (운영자가 직접 등록 → 바로 운영중)"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    if (await db.execute(select(Store.id).where(Store.admin_login_id == admin_login_id))).first():
        return templates.TemplateResponse(request=request, name="ops/store_form.html",
                                          context={"store": None, "mode": "create",
                                                   "error": "이미 사용 중인 로그인 아이디입니다."})

    store = Store(
        name=name.strip(), biz_no=biz_no.strip() or None, store_code=await _new_store_code(db),
        naver_review_url=naver_review_url.strip() or None,
        paper_width=paper_width if paper_width in (384, 576) else 576,
        status=StoreStatus.ACTIVE, admin_login_id=admin_login_id.strip(),
        staff_pin=(staff_pin.strip()[:4] or None),
    )
    store.set_password(admin_password)
    db.add(store)
    await db.flush()
    db.add(StoreSettings(store_id=store.id))
    await db.commit()
    return RedirectResponse(url="/ops/stores", status_code=303)


@router.get("/stores/{store_id}", response_class=HTMLResponse)
async def store_detail(request: Request, store_id: int, db: AsyncSession = Depends(get_db)):
    """매장 상세/수정 폼"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    store = (await db.execute(select(Store).where(Store.id == store_id))).scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="매장을 찾을 수 없습니다")
    view = {
        "id": store.id, "name": store.name, "biz_no": store.biz_no, "store_code": store.store_code,
        "naver_review_url": store.naver_review_url, "paper_width": store.paper_width,
        "status": store.status.value if hasattr(store.status, "value") else store.status,
        "staff_pin": store.staff_pin, "admin_login_id": store.admin_login_id,
    }
    return templates.TemplateResponse(request=request, name="ops/store_form.html",
                                      context={"store": view, "mode": "edit"})


@router.post("/stores/{store_id}")
async def store_update(
    request: Request,
    store_id: int,
    name: str = Form(None),
    biz_no: str = Form(None),
    naver_review_url: str = Form(None),
    paper_width: int = Form(None),
    status: str = Form(None),
    staff_pin: str = Form(None),
    admin_password: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """매장 수정"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    store = (await db.execute(select(Store).where(Store.id == store_id))).scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="매장을 찾을 수 없습니다")
    if name:
        store.name = name.strip()
    if biz_no is not None:
        store.biz_no = biz_no.strip() or None
    if naver_review_url is not None:
        store.naver_review_url = naver_review_url.strip() or None
    if paper_width in (384, 576):
        store.paper_width = paper_width
    if status in ("active", "paused"):
        store.status = StoreStatus(status)
    if staff_pin:
        store.staff_pin = staff_pin.strip()[:4]
    if admin_password:
        store.set_password(admin_password)
    await db.commit()
    return RedirectResponse(url=f"/ops/stores/{store_id}", status_code=303)


async def _set_store_status(db: AsyncSession, store_id: int, status: StoreStatus):
    store = (await db.execute(select(Store).where(Store.id == store_id))).scalar_one_or_none()
    if not store:
        return JSONResponse({"error": "매장을 찾을 수 없습니다"}, status_code=404)
    store.status = status
    await db.commit()
    return JSONResponse({"success": True, "status": status.value})


@router.post("/stores/{store_id}/pause")
async def store_pause(request: Request, store_id: int, db: AsyncSession = Depends(get_db)):
    """매장 일시정지"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await _set_store_status(db, store_id, StoreStatus.PAUSED)


@router.post("/stores/{store_id}/activate")
async def store_activate(request: Request, store_id: int, db: AsyncSession = Depends(get_db)):
    """매장 활성화"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await _set_store_status(db, store_id, StoreStatus.ACTIVE)


# ============ 활성화 코드 발급 (예전 방식 호환, 현재는 로그인 방식) ============

@router.post("/stores/{store_id}/activation-code")
async def generate_activation_code(request: Request, store_id: int, db: AsyncSession = Depends(get_db)):
    """에이전트 활성화 코드 발급 (8자리, 24시간 유효, 1회용)"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    import string
    alphabet = string.ascii_uppercase + string.digits
    code = ''.join(secrets.choice(alphabet) for _ in range(8))
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    db.add(Agent(store_id=store_id, activation_code=code, activation_expires_at=expires_at))
    await db.commit()

    return JSONResponse({"code": code, "expires_at": expires_at.isoformat(), "store_id": store_id})


# ============ 에이전트 상태 ============

async def _agent_rows(db: AsyncSession) -> list[dict]:
    agents = await _latest_agents(db)
    stores = (await db.execute(select(Store).where(Store.status == StoreStatus.ACTIVE).order_by(Store.name))).scalars().all()
    rows = []
    for s in stores:
        a = agents.get(s.id)
        status_, warning = agent_health(a)
        rows.append({
            "store_id": s.id, "store_name": s.name,
            "agent_id": a.id if a else None,
            "version": a.version if a else None,
            "capture_mode": a.capture_mode if a else None,
            "last_heartbeat_at": _aware(a.last_heartbeat_at).astimezone(KST) if a and a.last_heartbeat_at else None,
            "last_capture_at": _aware(a.last_capture_at).astimezone(KST) if a and a.last_capture_at else None,
            "queue_length": (a.queue_length or 0) if a else 0,
            "status": status_, "warning_message": warning,
        })
    order = {"offline": 0, "warning": 1, "online": 2}
    rows.sort(key=lambda r: order[r["status"]])
    return rows


@router.get("/agents", response_class=HTMLResponse)
async def agents_list(request: Request, db: AsyncSession = Depends(get_db)):
    """전체 매장 에이전트 상태 목록 (끊김·수신 0건·큐 쌓임 경고)"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)
    return templates.TemplateResponse(request=request, name="ops/agents.html",
                                      context={"agents": await _agent_rows(db)})


@router.get("/api/agents/status")
async def agents_status_api(request: Request, db: AsyncSession = Depends(get_db)):
    """에이전트 상태 API (실시간 갱신용)"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    rows = await _agent_rows(db)
    for r in rows:
        for k in ("last_heartbeat_at", "last_capture_at"):
            r[k] = r[k].isoformat() if r[k] else None
    return JSONResponse({"agents": rows})


# ============ 판별 불가 영수증 ============

@router.get("/receipts/unclassified", response_class=HTMLResponse)
async def unclassified_receipts(request: Request, db: AsyncSession = Depends(get_db)):
    """분류기가 판별하지 못한 영수증 (분류기 보정용)"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    rows = (await db.execute(
        select(Receipt, Store.name)
        .join(Store, Store.id == Receipt.store_id)
        .where(Receipt.classification == ReceiptClassification.UNCLASSIFIED,
               Receipt.status != ReceiptStatus.DISPOSED)
        .order_by(Receipt.created_at.desc()).limit(100)
    )).all()
    receipts = [{
        "id": r.id, "store_name": name, "created_at": _aware(r.created_at).astimezone(KST) if r.created_at else None,
        "approval_no": r.approval_no, "amount": r.amount, "card_issuer": r.card_issuer,
        "raw_text": r.raw_text, "image_path": r.image_path,
    } for r, name in rows]

    return templates.TemplateResponse(request=request, name="ops/unclassified.html", context={"receipts": receipts})


@router.post("/receipts/{receipt_id}/classify")
async def classify_receipt_manual(
    request: Request,
    receipt_id: str,
    classification: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """판별 불가 영수증 수동 분류: 정상이면 배정 대상, 그 외는 즉시 폐기"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    valid = ["normal", "cancel", "kitchen", "reprint", "cash", "discard"]
    if classification not in valid:
        return JSONResponse({"error": "Invalid classification"}, status_code=400)

    from uuid import UUID
    from app.services.disposal import _dispose_receipt
    try:
        rid = UUID(receipt_id)
    except ValueError:
        return JSONResponse({"error": "Invalid id"}, status_code=400)
    receipt = (await db.execute(select(Receipt).where(Receipt.id == rid))).scalar_one_or_none()
    if not receipt:
        return JSONResponse({"error": "Not found"}, status_code=404)

    if classification == "normal":
        receipt.classification = ReceiptClassification.NORMAL
    else:
        await _dispose_receipt(receipt, f"manual_{classification}", {"files_deleted": 0})
    await db.commit()

    return JSONResponse({"success": True, "classification": classification})


# ============ 매장별 통계 ============

@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request, db: AsyncSession = Depends(get_db)):
    """매장별 통계 페이지"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    from app.models.customer import StoreCustomer
    stores = (await db.execute(select(Store).order_by(Store.name))).scalars().all()
    stores_stats = []
    for s in stores:
        total = (await db.execute(select(func.count(ReviewSession.id)).where(ReviewSession.store_id == s.id))).scalar() or 0
        completed = (await db.execute(select(func.count(ReviewSession.id)).where(
            ReviewSession.store_id == s.id, ReviewSession.completed_at.isnot(None)))).scalar() or 0
        available = (await db.execute(select(func.count(Receipt.id)).where(
            Receipt.store_id == s.id, Receipt.status == ReceiptStatus.AVAILABLE))).scalar() or 0
        customers = (await db.execute(select(func.count()).select_from(StoreCustomer).where(
            StoreCustomer.store_id == s.id))).scalar() or 0
        stores_stats.append({
            "store_id": s.id, "store_name": s.name, "total_sessions": total,
            "completed_sessions": completed, "conversion_rate": (completed / total * 100) if total else 0.0,
            "available_receipts": available, "total_customers": customers,
        })

    return templates.TemplateResponse(request=request, name="ops/stats.html", context={"stores_stats": stores_stats})


@router.get("/api/stats/{store_id}")
async def store_stats_api(request: Request, store_id: int, db: AsyncSession = Depends(get_db)):
    """매장 상세 통계: 최근 30일 일별, 시간대별(한국 시간), 단계별 이탈"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    store = (await db.execute(select(Store).where(Store.id == store_id))).scalar_one_or_none()
    since = datetime.now(timezone.utc) - timedelta(days=30)
    sessions = (await db.execute(select(ReviewSession).where(
        ReviewSession.store_id == store_id, ReviewSession.started_at >= since))).scalars().all()

    daily: dict[str, int] = {}
    hourly = [0] * 24
    funnel = {"started": 0, "assigned": 0, "downloaded": 0, "redirected": 0, "completed": 0, "benefit_given": 0}
    for ss in sessions:
        t = _aware(ss.started_at).astimezone(KST)
        daily[t.strftime("%Y-%m-%d")] = daily.get(t.strftime("%Y-%m-%d"), 0) + 1
        hourly[t.hour] += 1
        funnel["started"] += 1
        funnel["assigned"] += 1 if ss.assigned_at or ss.receipt_id else 0
        funnel["downloaded"] += 1 if ss.downloaded_at else 0
        funnel["redirected"] += 1 if ss.redirected_at else 0
        funnel["completed"] += 1 if ss.completed_at else 0
        funnel["benefit_given"] += 1 if ss.benefit_given_at else 0

    return JSONResponse({
        "store_id": store_id,
        "store_name": store.name if store else None,
        "daily_sessions": [{"date": d, "count": c} for d, c in sorted(daily.items())],
        "hourly_distribution": hourly,
        "conversion_funnel": funnel,
    })


# ============ 설치 파일 관리 ============

@router.get("/installer", response_class=HTMLResponse)
async def installer_page(request: Request):
    """설치 파일 버전 관리 (서버 다운로드 폴더 기준)"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    import os
    import re as _re
    from app.services.release import get_release, sha256_of, INSTALLER_DIR, parse_version
    rel = get_release()
    found: dict[str, dict] = {}
    if os.path.isdir(INSTALLER_DIR):
        for fn in os.listdir(INSTALLER_DIR):
            m = _re.match(r"ReceiptTap_(?:Setup_|v)(\d+\.\d+\.\d+)\.(exe|zip)$", fn)
            if not m:
                continue
            v = found.setdefault(m.group(1), {"version": m.group(1), "files": []})
            v["files"].append(fn)
    versions = []
    for ver in sorted(found.values(), key=lambda x: parse_version(x["version"]), reverse=True):
        main = next((f for f in ver["files"] if f.endswith(".exe")), ver["files"][0])
        versions.append({
            "version": ver["version"], "filename": ", ".join(sorted(ver["files"])),
            "sha256": sha256_of(os.path.join(INSTALLER_DIR, main)),
            "release_date": datetime.fromtimestamp(os.path.getmtime(os.path.join(INSTALLER_DIR, main))),
            "download_count": 0, "is_latest": ver["version"] == rel.version,
        })

    return templates.TemplateResponse(request=request, name="ops/installer.html", context={"versions": versions})


@router.post("/installer/upload")
async def upload_installer(
    request: Request,
    version: str = Form(...),
    file: UploadFile = File(...)
):
    """새 설치 파일 업로드 (.exe = 첫 설치용, .zip = 자동 업데이트용)"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    import os
    import re as _re
    from app.services.release import INSTALLER_DIR
    if not _re.fullmatch(r"\d+\.\d+\.\d+", version or ""):
        return JSONResponse({"error": "버전은 1.2.3 형식으로 입력하세요"}, status_code=400)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".exe", ".zip"):
        return JSONResponse({"error": ".exe 또는 .zip 파일만 올릴 수 있습니다"}, status_code=400)

    filename = f"ReceiptTap_Setup_{version}.exe" if ext == ".exe" else f"ReceiptTap_v{version}.zip"
    os.makedirs(INSTALLER_DIR, exist_ok=True)
    filepath = os.path.join(INSTALLER_DIR, filename)
    contents = await file.read()
    with open(filepath + ".tmp", "wb") as f:
        f.write(contents)
    os.replace(filepath + ".tmp", filepath)

    return JSONResponse({"success": True, "version": version, "filename": filename,
                         "sha256": hashlib.sha256(contents).hexdigest()})


@router.post("/installer/{version}/set-latest")
async def set_latest_version(request: Request, version: str):
    """최신 버전 지정 → 사이트 다운로드·자동 업데이트에 즉시 반영"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    import os
    from app.services.release import INSTALLER_DIR, save_release, get_release
    setup = f"ReceiptTap_Setup_{version}.exe"
    package = f"ReceiptTap_v{version}.zip"
    has_setup = os.path.exists(os.path.join(INSTALLER_DIR, setup))
    has_pkg = os.path.exists(os.path.join(INSTALLER_DIR, package))
    if not has_pkg:
        return JSONResponse({"error": f"{package} 이 없습니다 (자동 업데이트용 zip 필요)"}, status_code=400)

    prev = get_release()
    save_release(version, setup if has_setup else None, package,
                 prev.notes if prev.version == version else f"v{version}",
                 datetime.now(KST).strftime("%Y-%m-%d"))
    return JSONResponse({"success": True, "latest_version": version})


# ============ 가입 신청 관리 ============

@router.get("/signups", response_class=HTMLResponse)
async def signups_list(request: Request, db: AsyncSession = Depends(get_db)):
    """가입 신청 목록 (승인 대기)"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    # 승인 대기 중인 매장 (status=paused)
    stmt = select(Store).where(Store.status == StoreStatus.PAUSED).order_by(Store.created_at.desc())
    result = await db.execute(stmt)
    pending_stores = result.scalars().all()

    # 승인 완료된 매장 (status=active) - 최근 20개
    stmt = select(Store).where(Store.status == StoreStatus.ACTIVE).order_by(Store.created_at.desc()).limit(20)
    result = await db.execute(stmt)
    approved_stores = result.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="ops/signups.html",
        context={
        
        "pending_stores": pending_stores,
        "approved_stores": approved_stores
    })


@router.post("/signups/{store_id}/approve")
async def approve_signup(request: Request, store_id: int, db: AsyncSession = Depends(get_db)):
    """가입 승인"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    stmt = select(Store).where(Store.id == store_id)
    result = await db.execute(stmt)
    store = result.scalar_one_or_none()

    if not store:
        return JSONResponse({"error": "매장을 찾을 수 없습니다"}, status_code=404)

    store.status = StoreStatus.ACTIVE
    await db.commit()

    # TODO: 승인 알림 문자 발송 (알리고 연동 후)
    # sms_message = f"[영수증리뷰] {store.name} 가입이 승인되었습니다. 로그인하여 프로그램을 다운로드하세요."
    # send_sms(store.phone, sms_message)

    return JSONResponse({
        "success": True,
        "store_id": store_id,
        "store_name": store.name,
        "message": "승인 완료"
    })


@router.post("/signups/{store_id}/reject")
async def reject_signup(request: Request, store_id: int, db: AsyncSession = Depends(get_db)):
    """가입 거절 (삭제)"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    stmt = select(Store).where(Store.id == store_id)
    result = await db.execute(stmt)
    store = result.scalar_one_or_none()

    if not store:
        return JSONResponse({"error": "매장을 찾을 수 없습니다"}, status_code=404)

    await db.delete(store)
    await db.commit()

    return JSONResponse({
        "success": True,
        "store_id": store_id,
        "message": "삭제 완료"
    })


@router.get("/api/signups/pending-count")
async def pending_count_api(request: Request, db: AsyncSession = Depends(get_db)):
    """승인 대기 건수 API (대시보드 실시간 갱신용)"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    stmt = select(func.count(Store.id)).where(Store.status == StoreStatus.PAUSED)
    result = await db.execute(stmt)
    count = result.scalar() or 0

    return JSONResponse({"pending_count": count})
