"""손님 모바일 웹 API 라우터"""
import hmac
import hashlib
import time
import secrets as py_secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models.store import Store, StoreSettings
from ..models.session import ReviewSession, SessionStatus
from ..models.customer import ConsentType, ConsentAction
from ..services.customers import CustomerService
from ..services.assignment import AssignmentService, NoReceiptAvailableError
from ..review.text_generator import TextGenerator


router = APIRouter(tags=["customer"])
templates = Jinja2Templates(directory="app/templates")


# ============================================================
# 페이지 라우트 (HTML 템플릿)
# ============================================================

@router.get("/t/{store_code}/{table_no}", response_class=HTMLResponse)
async def phone_input_page(
    request: Request,
    store_code: str,
    table_no: str,
    db: AsyncSession = Depends(get_db)
):
    """화면 1: 전화번호 입력"""
    store = await get_store_by_code(store_code, db)
    store_settings = await get_store_settings(store.id, db)

    store_data = {
        "id": store.id,
        "name": store.name,
        "store_code": store.store_code,
        "naver_review_url": store.naver_review_url,
        "settings": {
            "benefit_text": store_settings.benefit_text if store_settings else "리뷰 작성 시 특별 혜택!",
        }
    }

    return templates.TemplateResponse(
        request=request,
        name="customer/phone.html",
        context={"store": store_data, "table_no": table_no}
    )


@router.get("/t/{store_code}/{table_no}/keywords", response_class=HTMLResponse)
async def keywords_page(
    request: Request,
    store_code: str,
    table_no: str,
    db: AsyncSession = Depends(get_db)
):
    """화면 2: 키워드 선택"""
    store = await get_store_by_code(store_code, db)
    store_settings = await get_store_settings(store.id, db)

    keywords = store_settings.keywords if store_settings and store_settings.keywords else [
        {"label": "맛있어요", "default": True},
        {"label": "친절해요", "default": True},
        {"label": "분위기 좋아요", "default": False},
        {"label": "가성비 좋아요", "default": False},
    ]

    store_data = {
        "id": store.id,
        "name": store.name,
        "store_code": store.store_code,
        "naver_review_url": store.naver_review_url,
        "settings": {}
    }

    return templates.TemplateResponse(
        request=request,
        name="customer/keywords.html",
        context={"store": store_data, "table_no": table_no, "keywords": keywords}
    )


@router.get("/t/{store_code}/{table_no}/result", response_class=HTMLResponse)
async def result_page(
    request: Request,
    store_code: str,
    table_no: str,
    db: AsyncSession = Depends(get_db)
):
    """화면 3: 결과 (영수증 + 문구)"""
    store = await get_store_by_code(store_code, db)

    # TODO: 세션에서 실제 데이터 가져오기
    review_text = "정말 맛있었어요! 직원분들이 친절하셔서 기분 좋게 식사했습니다. 다음에 또 올게요."
    receipt_image_url = "/static/images/sample_receipt.png"

    store_data = {
        "id": store.id,
        "name": store.name,
        "store_code": store.store_code,
        "naver_review_url": store.naver_review_url,
        "settings": {}
    }

    return templates.TemplateResponse(
        request=request,
        name="customer/result.html",
        context={"store": store_data, "table_no": table_no, "review_text": review_text, "receipt_image_url": receipt_image_url}
    )


@router.get("/t/{store_code}/{table_no}/complete", response_class=HTMLResponse)
async def complete_page(
    request: Request,
    store_code: str,
    table_no: str,
    db: AsyncSession = Depends(get_db)
):
    """화면 5: 완료"""
    store = await get_store_by_code(store_code, db)
    store_settings = await get_store_settings(store.id, db)

    completion_code = ''.join([str(py_secrets.randbelow(10)) for _ in range(6)])

    store_data = {
        "id": store.id,
        "name": store.name,
        "store_code": store.store_code,
        "naver_review_url": store.naver_review_url,
        "settings": {
            "benefit_text": store_settings.benefit_text if store_settings else "직원에게 이 화면을 보여주세요!",
        }
    }

    return templates.TemplateResponse(
        request=request,
        name="customer/complete.html",
        context={"store": store_data, "table_no": table_no, "completion_code": completion_code}
    )


# ============================================================
# API 라우트
# ============================================================


class SessionStartRequest(BaseModel):
    phone: str
    marketing_opt_in: bool = False
    table_no: Optional[str] = None
    device_id: Optional[str] = None


class SessionStartResponse(BaseModel):
    session_id: UUID
    is_returning: bool
    existing_receipt_id: Optional[UUID] = None
    existing_text: Optional[str] = None


class KeywordsRequest(BaseModel):
    keywords: list[str]


class AssignResponse(BaseModel):
    receipt_id: UUID
    image_token: str
    generated_text: str
    completion_code: str


class RegenerateResponse(BaseModel):
    generated_text: str
    regenerate_count: int


class EventRequest(BaseModel):
    event: str  # downloaded, redirected, completed


class BenefitRequest(BaseModel):
    pin: str


def generate_image_token(session_id: UUID, receipt_id: UUID) -> str:
    """이미지 접근용 서명 토큰 생성 (24시간 유효)"""
    settings = get_settings()
    expires = int(time.time()) + 86400
    payload = f"{session_id}:{receipt_id}:{expires}"
    signature = hmac.new(
        settings.SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    return f"{payload}:{signature}"


def verify_image_token(token: str, session_id: UUID, receipt_id: UUID) -> bool:
    """이미지 토큰 검증"""
    try:
        parts = token.split(":")
        if len(parts) != 4:
            return False

        token_session, token_receipt, expires_str, signature = parts

        if token_session != str(session_id) or token_receipt != str(receipt_id):
            return False

        if int(expires_str) < time.time():
            return False

        settings = get_settings()
        payload = f"{token_session}:{token_receipt}:{expires_str}"
        expected = hmac.new(
            settings.SECRET_KEY.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()[:16]

        return hmac.compare_digest(signature, expected)
    except Exception:
        return False


async def get_store_by_code(store_code: str, db: AsyncSession) -> Store:
    """store_code로 매장 조회"""
    result = await db.execute(
        select(Store).where(Store.store_code == store_code)
    )
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="매장을 찾을 수 없습니다")
    return store


async def get_store_settings(store_id: int, db: AsyncSession) -> Optional[StoreSettings]:
    """매장 설정 조회"""
    result = await db.execute(
        select(StoreSettings).where(StoreSettings.store_id == store_id)
    )
    return result.scalar_one_or_none()


@router.post("/api/v1/session/start", response_model=SessionStartResponse)
async def start_session(
    request: SessionStartRequest,
    store_code: str = Query(...),
    req: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    세션 시작 - 전화번호 입력 + 동의
    같은 번호로 오늘 이미 참여한 경우 기존 세션 반환
    """
    store = await get_store_by_code(store_code, db)
    store_settings = await get_store_settings(store.id, db)

    customer_service = CustomerService(db)
    assignment_service = AssignmentService(db)

    customer = await customer_service.get_or_create_customer(request.phone)

    await customer_service.get_or_create_store_customer(
        store.id,
        customer.id,
        request.marketing_opt_in
    )

    ip = req.client.host if req else None
    user_agent = req.headers.get("user-agent") if req else None

    await customer_service.record_consent(
        customer.id, store.id,
        ConsentType.REQUIRED_PRIVACY, ConsentAction.AGREE,
        ip=ip, user_agent=user_agent
    )

    if request.marketing_opt_in:
        await customer_service.record_consent(
            customer.id, store.id,
            ConsentType.MARKETING, ConsentAction.AGREE,
            ip=ip, user_agent=user_agent
        )

    cutoff = store_settings.business_day_cutoff if store_settings else "05:00"
    business_day_start = assignment_service.get_business_day_start(cutoff)

    existing = await customer_service.check_today_participation(
        store.id, customer.id, business_day_start
    )

    if existing:
        await db.commit()
        return SessionStartResponse(
            session_id=existing.id,
            is_returning=True,
            existing_receipt_id=existing.receipt_id,
            existing_text=existing.generated_text
        )

    session = await assignment_service.create_session(
        store.id, customer.id,
        table_no=request.table_no,
        device_id=request.device_id
    )

    await db.commit()

    return SessionStartResponse(
        session_id=session.id,
        is_returning=False
    )


@router.post("/api/v1/session/{session_id}/keywords")
async def save_keywords(
    session_id: UUID,
    request: KeywordsRequest,
    db: AsyncSession = Depends(get_db)
):
    """키워드 저장"""
    result = await db.execute(
        select(ReviewSession).where(ReviewSession.id == session_id)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")

    session.selected_keywords = request.keywords
    await db.commit()

    return {"status": "ok", "keywords": request.keywords}


@router.post("/api/v1/session/{session_id}/assign", response_model=AssignResponse)
async def assign_receipt(
    session_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """영수증 배정 + 문구 생성"""
    result = await db.execute(
        select(ReviewSession).where(ReviewSession.id == session_id)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")

    if session.receipt_id:
        raise HTTPException(status_code=400, detail="이미 영수증이 배정되었습니다")

    store_settings = await get_store_settings(session.store_id, db)

    assignment_service = AssignmentService(db)
    text_generator = TextGenerator(db)

    try:
        receipt = await assignment_service.assign_receipt(session, store_settings)
    except NoReceiptAvailableError:
        raise HTTPException(
            status_code=503,
            detail="사용 가능한 영수증이 없습니다. 잠시 후 다시 시도해주세요."
        )

    keywords = session.selected_keywords or []
    generated_text = await text_generator.generate(
        session.store_id,
        keywords,
        store_settings
    )
    session.generated_text = generated_text

    await db.commit()

    return AssignResponse(
        receipt_id=receipt.id,
        image_token=generate_image_token(session.id, receipt.id),
        generated_text=generated_text,
        completion_code=session.completion_code
    )


@router.post("/api/v1/session/{session_id}/regenerate", response_model=RegenerateResponse)
async def regenerate_text(
    session_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """다른 문구 생성 (세션당 최대 10회)"""
    result = await db.execute(
        select(ReviewSession).where(ReviewSession.id == session_id)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")

    if not session.generated_text:
        raise HTTPException(status_code=400, detail="먼저 영수증을 배정받아야 합니다")

    store_settings = await get_store_settings(session.store_id, db)
    text_generator = TextGenerator(db)

    keywords = session.selected_keywords or []
    new_text, new_count = await text_generator.regenerate(
        session.store_id,
        keywords,
        session.generated_text,
        session.regenerate_count,
        store_settings
    )

    session.generated_text = new_text
    session.regenerate_count = new_count
    await db.commit()

    return RegenerateResponse(
        generated_text=new_text,
        regenerate_count=new_count
    )


@router.post("/api/v1/session/{session_id}/event")
async def record_event(
    session_id: UUID,
    request: EventRequest,
    db: AsyncSession = Depends(get_db)
):
    """이벤트 기록 (downloaded, redirected, completed)"""
    result = await db.execute(
        select(ReviewSession).where(ReviewSession.id == session_id)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")

    event_map = {
        "downloaded": SessionStatus.DOWNLOADED,
        "redirected": SessionStatus.REDIRECTED,
        "completed": SessionStatus.COMPLETED,
    }

    if request.event not in event_map:
        raise HTTPException(status_code=400, detail="유효하지 않은 이벤트입니다")

    assignment_service = AssignmentService(db)
    await assignment_service.update_session_status(session, event_map[request.event])
    await db.commit()

    return {"status": "ok", "event": request.event}


@router.post("/api/v1/session/{session_id}/benefit")
async def confirm_benefit(
    session_id: UUID,
    request: BenefitRequest,
    db: AsyncSession = Depends(get_db)
):
    """혜택 지급 확인 (직원 PIN 검증)"""
    result = await db.execute(
        select(ReviewSession).where(ReviewSession.id == session_id)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")

    assignment_service = AssignmentService(db)

    if not await assignment_service.verify_staff_pin(session.store_id, request.pin):
        raise HTTPException(status_code=403, detail="PIN이 올바르지 않습니다")

    await assignment_service.update_session_status(session, SessionStatus.BENEFIT_GIVEN)
    await db.commit()

    return {"status": "ok", "benefit_given": True}


@router.get("/api/v1/receipt-image/{token}")
async def get_receipt_image(
    token: str,
    session_id: UUID = Query(...),
    receipt_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """영수증 이미지 반환 (서명 토큰 검증)"""
    if not verify_image_token(token, session_id, receipt_id):
        raise HTTPException(status_code=403, detail="유효하지 않은 토큰입니다")

    from ..models.receipt import Receipt
    result = await db.execute(
        select(Receipt).where(Receipt.id == receipt_id)
    )
    receipt = result.scalar_one_or_none()

    if not receipt or not receipt.image_path:
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다")

    return FileResponse(
        receipt.image_path,
        media_type="image/png",
        filename=f"receipt_{receipt_id}.png"
    )
