"""
운영자 웹 라우터 (광고토대왕 전용)
Phase 5: 매장 관리, 에이전트 관리, 통계
"""
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, and_, select
from pydantic import BaseModel

from app.db import get_db
from app.models.store import Store, StoreStatus

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

OPS_USERNAME = "admin"
OPS_PASSWORD_HASH = hashlib.sha256("ReceiptReview2026!".encode()).hexdigest()


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
    """운영자 로그인 처리"""
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    if username == OPS_USERNAME and password_hash == OPS_PASSWORD_HASH:
        request.session["ops_authenticated"] = True
        return RedirectResponse(url="/ops/dashboard", status_code=303)

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

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """운영자 대시보드"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    # TODO: DB에서 실제 통계 조회
    stats = {
        "total_stores": 0,
        "active_stores": 0,
        "online_agents": 0,
        "offline_agents": 0,
        "today_sessions": 0,
        "today_completed": 0,
        "unclassified_count": 0
    }

    return templates.TemplateResponse(
        request=request,
        name="ops/dashboard.html",
        context={
        
        "stats": stats
    })


# ============ 매장 관리 ============

@router.get("/stores", response_class=HTMLResponse)
async def stores_list(request: Request):
    """매장 목록"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    # TODO: DB에서 매장 목록 조회
    stores = []

    return templates.TemplateResponse(
        request=request,
        name="ops/stores.html",
        context={
        
        "stores": stores
    })


@router.get("/stores/new", response_class=HTMLResponse)
async def store_new_form(request: Request):
    """매장 등록 폼"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="ops/store_form.html",
        context={
        
        "store": None,
        "mode": "create"
    })


@router.post("/stores/new")
async def store_create(
    request: Request,
    name: str = Form(...),
    biz_no: str = Form(...),
    naver_review_url: str = Form(...),
    paper_width: int = Form(576),
    admin_login_id: str = Form(...),
    admin_password: str = Form(...),
    staff_pin: str = Form(...)
):
    """매장 등록"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    # TODO: DB에 매장 저장
    # store_code 자동 생성
    store_code = secrets.token_urlsafe(6)[:8]

    return RedirectResponse(url="/ops/stores", status_code=303)


@router.get("/stores/{store_id}", response_class=HTMLResponse)
async def store_detail(request: Request, store_id: int):
    """매장 상세/수정 폼"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    # TODO: DB에서 매장 조회
    store = None

    return templates.TemplateResponse(
        request=request,
        name="ops/store_form.html",
        context={
        
        "store": store,
        "mode": "edit"
    })


@router.post("/stores/{store_id}")
async def store_update(
    request: Request,
    store_id: int,
    name: str = Form(None),
    biz_no: str = Form(None),
    naver_review_url: str = Form(None),
    paper_width: int = Form(None),
    status: str = Form(None),
    staff_pin: str = Form(None)
):
    """매장 수정"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    # TODO: DB 업데이트

    return RedirectResponse(url=f"/ops/stores/{store_id}", status_code=303)


@router.post("/stores/{store_id}/pause")
async def store_pause(request: Request, store_id: int):
    """매장 일시정지"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # TODO: status = "paused" 업데이트
    return JSONResponse({"success": True, "status": "paused"})


@router.post("/stores/{store_id}/activate")
async def store_activate(request: Request, store_id: int):
    """매장 활성화"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # TODO: status = "active" 업데이트
    return JSONResponse({"success": True, "status": "active"})


# ============ 활성화 코드 발급 ============

@router.post("/stores/{store_id}/activation-code")
async def generate_activation_code(request: Request, store_id: int):
    """에이전트 활성화 코드 발급 (8자리, 24시간 유효)"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # 8자리 코드 생성 (영문 대문자 + 숫자)
    import string
    alphabet = string.ascii_uppercase + string.digits
    code = ''.join(secrets.choice(alphabet) for _ in range(8))

    expires_at = datetime.utcnow() + timedelta(hours=24)

    # TODO: DB에 저장 (agents 테이블의 activation_code 필드)

    return JSONResponse({
        "code": code,
        "expires_at": expires_at.isoformat(),
        "store_id": store_id
    })


# ============ 에이전트 상태 ============

@router.get("/agents", response_class=HTMLResponse)
async def agents_list(request: Request):
    """전체 매장 에이전트 상태 목록"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    # TODO: DB에서 에이전트 상태 조회
    agents = []

    # 상태 판별 로직:
    # - online: 마지막 하트비트 5분 이내
    # - warning: 하트비트 5-30분 또는 캡처 0건 또는 큐 > 100
    # - offline: 하트비트 30분 초과

    return templates.TemplateResponse(
        request=request,
        name="ops/agents.html",
        context={
        
        "agents": agents
    })


@router.get("/api/agents/status")
async def agents_status_api(request: Request):
    """에이전트 상태 API (실시간 갱신용)"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # TODO: DB에서 조회
    agents = []

    return JSONResponse({"agents": agents})


# ============ 미분류 영수증 ============

@router.get("/receipts/unclassified", response_class=HTMLResponse)
async def unclassified_receipts(request: Request):
    """미분류(unclassified) 영수증 확인 화면"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    # TODO: DB에서 classification='unclassified' 영수증 조회
    receipts = []

    return templates.TemplateResponse(
        request=request,
        name="ops/unclassified.html",
        context={
        
        "receipts": receipts
    })


@router.post("/receipts/{receipt_id}/classify")
async def classify_receipt(
    request: Request,
    receipt_id: str,
    classification: str = Form(...)
):
    """영수증 수동 분류"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    valid_classifications = ["normal", "cancel", "kitchen", "reprint", "cash", "discard"]
    if classification not in valid_classifications:
        return JSONResponse({"error": "Invalid classification"}, status_code=400)

    # TODO: DB 업데이트

    return JSONResponse({"success": True, "classification": classification})


# ============ 매장별 통계 ============

@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    """매장별 통계 페이지"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    # TODO: DB에서 통계 조회
    stores_stats = []

    return templates.TemplateResponse(
        request=request,
        name="ops/stats.html",
        context={
        
        "stores_stats": stores_stats
    })


@router.get("/api/stats/{store_id}")
async def store_stats_api(request: Request, store_id: int):
    """매장 상세 통계 API"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # TODO: DB에서 상세 통계 조회
    stats = {
        "store_id": store_id,
        "daily_sessions": [],  # 최근 30일
        "hourly_distribution": [],  # 시간대별 분포
        "conversion_funnel": {
            "started": 0,
            "assigned": 0,
            "downloaded": 0,
            "redirected": 0,
            "completed": 0,
            "benefit_given": 0
        }
    }

    return JSONResponse(stats)


# ============ 설치 파일 관리 ============

@router.get("/installer", response_class=HTMLResponse)
async def installer_page(request: Request):
    """설치 파일 버전 관리 페이지"""
    if not verify_ops_session(request):
        return RedirectResponse(url="/ops/login", status_code=303)

    # TODO: 설치 파일 목록 조회
    versions = []

    return templates.TemplateResponse(
        request=request,
        name="ops/installer.html",
        context={
        
        "versions": versions
    })


@router.post("/installer/upload")
async def upload_installer(
    request: Request,
    version: str = Form(...),
    file: UploadFile = File(...)
):
    """새 설치 파일 업로드"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # 파일 저장
    import os
    upload_dir = "uploads/installers"
    os.makedirs(upload_dir, exist_ok=True)

    filename = f"ReceiptTap_{version}.exe"
    filepath = os.path.join(upload_dir, filename)

    contents = await file.read()

    # SHA-256 해시 계산
    sha256_hash = hashlib.sha256(contents).hexdigest()

    with open(filepath, "wb") as f:
        f.write(contents)

    # TODO: DB에 버전 정보 저장

    return JSONResponse({
        "success": True,
        "version": version,
        "filename": filename,
        "sha256": sha256_hash
    })


@router.post("/installer/{version}/set-latest")
async def set_latest_version(request: Request, version: str):
    """최신 버전 설정"""
    if not verify_ops_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # TODO: DB에서 latest 플래그 업데이트

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
