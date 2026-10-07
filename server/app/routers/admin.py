"""
점주 관리자 웹 라우터
"""
from datetime import datetime, date, timedelta
from typing import Optional
import secrets
import hashlib
import io
import zipfile

from fastapi import APIRouter, Request, Response, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# 템플릿 설정
templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/admin", tags=["admin"])


# ============ Models ============

class PhrasesUpdate(BaseModel):
    keywords: list
    signature_menus: list
    templates: list
    text_min_len: int
    text_max_len: int


class SettingsUpdate(BaseModel):
    naver_review_url: Optional[str] = None
    benefit_text: Optional[str] = None
    staff_pin: Optional[str] = None
    primary_color: Optional[str] = None
    paper_width: Optional[int] = None
    assignment_policy: Optional[str] = None
    business_day_cutoff: Optional[str] = None
    hourly_assign_limit: Optional[int] = None
    daily_assign_limit: Optional[int] = None
    new_password: Optional[str] = None


# ============ Session Management ============

def get_current_store(request: Request):
    """세션에서 현재 로그인된 매장 정보를 가져옵니다."""
    store_id = request.session.get("store_id")
    if not store_id:
        return None

    # TODO: DB에서 매장 정보 조회
    # 임시로 더미 데이터 반환
    return {
        "id": store_id,
        "name": "맛있는 식당",
        "biz_no": "123-45-67890",
        "store_code": "tasty123",
        "naver_review_url": "https://naver.me/xOmvlCzr",
        "paper_width": 576,
        "admin_login_id": "admin",
        "staff_pin": "1234"
    }


def require_login(request: Request):
    """로그인 필수 체크"""
    store = get_current_store(request)
    if not store:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    return store


# ============ Auth Routes ============

@router.get("/login", response_class=HTMLResponse, name="admin_login")
async def login_page(request: Request, error: Optional[str] = None):
    """로그인 페이지"""
    return templates.TemplateResponse("admin/login.html", {
        "request": request,
        "error": error
    })


@router.post("/login", name="admin_login_post")
async def login(request: Request, login_id: str = Form(...), password: str = Form(...)):
    """로그인 처리"""
    # TODO: 실제 DB에서 검증
    # 임시로 admin/admin으로 로그인
    if login_id == "admin" and password == "admin":
        request.session["store_id"] = 1
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    return templates.TemplateResponse("admin/login.html", {
        "request": request,
        "error": "아이디 또는 비밀번호가 올바르지 않습니다."
    })


@router.get("/logout", name="admin_logout")
async def logout(request: Request):
    """로그아웃"""
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=302)


# ============ Dashboard ============

@router.get("/dashboard", response_class=HTMLResponse, name="admin_dashboard")
async def dashboard(request: Request):
    """대시보드"""
    store = get_current_store(request)
    if not store:
        return RedirectResponse(url="/admin/login", status_code=302)

    # TODO: 실제 통계 데이터 조회
    stats = {
        "today_sessions": 23,
        "sessions_change": 15,
        "available_receipts": 12,
        "completed": 18,
        "benefits_given": 15,
        "step_phone": 45,
        "step_keyword": 42,
        "step_assign": 40,
        "step_download": 35,
        "step_redirect": 32,
        "step_complete": 25,
        "step_benefit": 18
    }

    recent_activities = [
        {"time": "14:32", "phone_masked": "010-****-1234", "amount": 28000, "status_class": "success", "status_text": "혜택지급"},
        {"time": "14:28", "phone_masked": "010-****-5678", "amount": 35000, "status_class": "info", "status_text": "리뷰완료"},
        {"time": "14:15", "phone_masked": "010-****-9012", "amount": 22000, "status_class": "warning", "status_text": "진행중"},
    ]

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "store": store,
        "active_menu": "dashboard",
        "today": date.today(),
        "stats": stats,
        "agent_online": True,
        "last_heartbeat": "방금 전",
        "agent_version": "1.0.0",
        "capture_mode": "시리얼(COM)",
        "queue_length": 0,
        "today_receipts": 45,
        "recent_activities": recent_activities
    })


# ============ Phrases ============

@router.get("/phrases", response_class=HTMLResponse, name="admin_phrases")
async def phrases_page(request: Request):
    """문구 설정 페이지"""
    store = get_current_store(request)
    if not store:
        return RedirectResponse(url="/admin/login", status_code=302)

    # TODO: DB에서 설정 조회
    keywords = [
        {"label": "맛있어요", "default": True},
        {"label": "친절해요", "default": True},
        {"label": "분위기 좋아요", "default": False},
        {"label": "가성비 좋아요", "default": False},
        {"label": "재방문 의사 있어요", "default": False}
    ]

    signature_menus = ["돼지김치찌개", "계란말이", "된장찌개"]

    templates_list = [
        "{메뉴} 정말 맛있었어요! {키워드1} 다음에 또 올게요.",
        "오늘 {메뉴} 먹었는데 {키워드1} {키워드2} 추천합니다.",
        "{키워드1} 분위기도 좋고 {메뉴}도 최고였어요."
    ]

    return templates.TemplateResponse("admin/phrases.html", {
        "request": request,
        "store": store,
        "active_menu": "phrases",
        "keywords": keywords,
        "signature_menus": signature_menus,
        "templates": templates_list,
        "text_min_len": 30,
        "text_max_len": 150
    })


@router.post("/phrases/save", name="admin_save_phrases")
async def save_phrases(request: Request, data: PhrasesUpdate):
    """문구 설정 저장"""
    store = get_current_store(request)
    if not store:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    # TODO: DB에 저장
    return JSONResponse({"success": True})


# ============ Settings ============

@router.get("/settings", response_class=HTMLResponse, name="admin_settings")
async def settings_page(request: Request):
    """매장 설정 페이지"""
    store = get_current_store(request)
    if not store:
        return RedirectResponse(url="/admin/login", status_code=302)

    # TODO: DB에서 설정 조회
    settings = {
        "benefit_text": "리뷰 작성 시 음료 1잔 서비스",
        "primary_color": "#03C75A",
        "assignment_policy": "latest_same_day",
        "business_day_cutoff": "05:00",
        "hourly_assign_limit": 50,
        "daily_assign_limit": 200
    }

    return templates.TemplateResponse("admin/settings.html", {
        "request": request,
        "store": store,
        "active_menu": "settings",
        "settings": settings
    })


@router.post("/settings/save", name="admin_save_settings")
async def save_settings(request: Request, data: SettingsUpdate):
    """매장 설정 저장"""
    store = get_current_store(request)
    if not store:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    # TODO: DB에 저장
    # 비밀번호 변경 시 해시 처리
    if data.new_password:
        # password_hash = hashlib.sha256(data.new_password.encode()).hexdigest()
        pass

    return JSONResponse({"success": True})


# ============ Customers ============

@router.get("/customers", response_class=HTMLResponse, name="admin_customers")
async def customers_page(request: Request, page: int = 1):
    """고객 목록 페이지"""
    store = get_current_store(request)
    if not store:
        return RedirectResponse(url="/admin/login", status_code=302)

    # TODO: DB에서 고객 목록 조회
    customers = [
        {
            "phone_masked": "010-****-1234",
            "first_visit_at": datetime(2026, 10, 1),
            "last_visit_at": datetime(2026, 10, 7),
            "visit_count": 3,
            "marketing_opt_in": True
        },
        {
            "phone_masked": "010-****-5678",
            "first_visit_at": datetime(2026, 10, 5),
            "last_visit_at": datetime(2026, 10, 5),
            "visit_count": 1,
            "marketing_opt_in": False
        },
        {
            "phone_masked": "010-****-9012",
            "first_visit_at": datetime(2026, 10, 7),
            "last_visit_at": datetime(2026, 10, 7),
            "visit_count": 1,
            "marketing_opt_in": True
        }
    ]

    stats = {
        "total": 156,
        "opted_in": 98,
        "returning": 45,
        "new_this_month": 32
    }

    return templates.TemplateResponse("admin/customers.html", {
        "request": request,
        "store": store,
        "active_menu": "customers",
        "customers": customers,
        "stats": stats,
        "current_page": page,
        "total_pages": 5
    })


# ============ Tables ============

@router.get("/tables", response_class=HTMLResponse, name="admin_tables")
async def tables_page(request: Request):
    """테이블 안내판 페이지"""
    store = get_current_store(request)
    if not store:
        return RedirectResponse(url="/admin/login", status_code=302)

    return templates.TemplateResponse("admin/tables.html", {
        "request": request,
        "store": store,
        "active_menu": "tables",
        "table_count": 10,
        "start_number": 1,
        "benefit_text": "리뷰 작성 시 음료 1잔 서비스"
    })


@router.get("/tables/download", name="admin_download_tables")
async def download_tables(
    request: Request,
    format: str = "pdf",
    count: int = 10,
    start: int = 1
):
    """테이블 안내판 다운로드"""
    store = get_current_store(request)
    if not store:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    # TODO: 실제 PDF/PNG 생성 로직
    # 지금은 플레이스홀더 응답

    if format == "pdf":
        # PDF 생성 (추후 구현)
        content = b"PDF placeholder"
        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=tables_{start}-{start+count-1}.pdf"
            }
        )
    else:
        # PNG ZIP 생성
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for i in range(start, start + count):
                # 플레이스홀더 PNG
                zip_file.writestr(f"table_{i}.png", b"PNG placeholder")

        zip_buffer.seek(0)
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=tables_{start}-{start+count-1}.zip"
            }
        )
