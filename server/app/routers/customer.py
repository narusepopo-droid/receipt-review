"""손님 모바일 웹 API 라우터"""
import hmac
import hashlib
import time
import secrets as py_secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Query, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator
import re
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

# 손님 진행 상태를 기억하는 쿠키 (QR 을 다시 찍어도 진행 중인 화면으로 복귀)
SESSION_COOKIE = "rr_sid"
SESSION_COOKIE_MAX_AGE = 24 * 3600


def set_session_cookie(response: Response, session_id) -> None:
    response.set_cookie(
        SESSION_COOKIE, str(session_id), max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True, samesite="lax", secure=get_settings().SESSION_HTTPS_ONLY,
    )


async def current_session(request: Request, store_id: int, db: AsyncSession,
                          sid: Optional[str] = None) -> Optional[ReviewSession]:
    """쿠키(또는 ?sid=)의 세션 중 이 매장·오늘 영업일 것만 인정"""
    raw = sid or request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        session_id = UUID(raw)
    except ValueError:
        return None
    session = (await db.execute(select(ReviewSession).where(ReviewSession.id == session_id))).scalar_one_or_none()
    if not session or session.store_id != store_id:
        return None
    store_settings = await get_store_settings(store_id, db)
    cutoff = store_settings.business_day_cutoff if store_settings else "05:00"
    started = session.started_at
    if started is not None and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if started is None or started < AssignmentService(db).get_business_day_start(cutoff):
        return None
    return session


def receipt_image_url(session: ReviewSession) -> str:
    token = generate_image_token(session.id, session.receipt_id)
    return f"/api/v1/receipt-image/{token}?session_id={session.id}&receipt_id={session.receipt_id}"


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
    """화면 1: 전화번호 입력 (오늘 이미 영수증을 받은 손님은 결과 화면으로)"""
    store = await get_store_by_code(store_code, db)
    store_settings = await get_store_settings(store.id, db)

    session = await current_session(request, store.id, db)
    if session and session.receipt_id:
        return RedirectResponse(url=f"/t/{store_code}/{table_no}/result", status_code=302)

    store_data = {
        "id": store.id,
        "name": store.name,
        "store_code": store.store_code,
        "naver_review_url": store.naver_review_url,
        "settings": {
            "benefit_text": store_settings.benefit_text if store_settings else "리뷰 작성 시 특별 혜택!",
        }
    }

    from ..services.otp import get_options
    phone_verify = (await get_options(db, store.id)).phone_verify

    return templates.TemplateResponse(
        request=request,
        name="customer/phone.html",
        context={"store": store_data, "table_no": table_no, "phone_verify": phone_verify}
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
        context={"store": store_data, "table_no": table_no, "keywords": keywords,
                 "session_id": str(session.id) if (session := await current_session(request, store.id, db)) else ""}
    )


@router.get("/t/{store_code}/{table_no}/result", response_class=HTMLResponse)
async def result_page(
    request: Request,
    store_code: str,
    table_no: str,
    db: AsyncSession = Depends(get_db)
):
    """화면 3: 결과 (실제 배정된 영수증 + 문구). 아직 배정 전이면 여기서 배정"""
    store = await get_store_by_code(store_code, db)
    session = await current_session(request, store.id, db, sid=request.query_params.get("sid"))
    if not session:
        return RedirectResponse(url=f"/t/{store_code}/{table_no}", status_code=302)

    no_receipt = False
    if not session.receipt_id:
        store_settings = await get_store_settings(store.id, db)
        try:
            await AssignmentService(db).assign_receipt(session, store_settings)
            session.generated_text = await TextGenerator(db).generate(
                store.id, session.selected_keywords or [], store_settings)
            await db.commit()
        except NoReceiptAvailableError:
            # 배정 단계는 영수증을 못 찾으면 아무것도 바꾸지 않음 (롤백 불필요)
            no_receipt = True

    review_text = session.generated_text or ""
    image_url = receipt_image_url(session) if session.receipt_id else ""

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
        context={"store": store_data, "table_no": table_no, "review_text": review_text,
                 "receipt_image_url": image_url, "no_receipt": no_receipt, "session_id": str(session.id)}
    )


@router.get("/t/{store_code}/{table_no}/complete", response_class=HTMLResponse)
async def complete_page(
    request: Request,
    store_code: str,
    table_no: str,
    db: AsyncSession = Depends(get_db)
):
    """화면 5: 완료 (손님이 [리뷰 등록 완료]를 누르면 들어옴 → completed 기록)"""
    store = await get_store_by_code(store_code, db)
    store_settings = await get_store_settings(store.id, db)

    session = await current_session(request, store.id, db)
    if session and session.receipt_id and session.status not in (SessionStatus.COMPLETED, SessionStatus.BENEFIT_GIVEN):
        await AssignmentService(db).update_session_status(session, SessionStatus.COMPLETED)
        await db.commit()
    completion_code = (session.completion_code if session and session.completion_code
                       else ''.join([str(py_secrets.randbelow(10)) for _ in range(6)]))

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
        context={"store": store_data, "table_no": table_no, "completion_code": completion_code,
                 "session_id": str(session.id) if session else ""}
    )


# ============================================================
# API 라우트
# ============================================================


class SessionStartRequest(BaseModel):
    phone: str
    marketing_opt_in: bool = False
    table_no: Optional[str] = None
    device_id: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def _valid_phone(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v or "")
        if not re.fullmatch(r"01[016789]\d{7,8}", digits):
            raise ValueError("휴대폰 번호를 정확히 입력해주세요")
        return digits


class ConsentWithdrawRequest(BaseModel):
    phone: str
    store_code: str


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
    event: Optional[str] = None       # downloaded, redirected, completed
    event_type: Optional[str] = None  # (예전 스크립트 호환)


class TextUpdateRequest(BaseModel):
    text: str


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
    response: Response,
    store_code: str = Query(...),
    req: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    세션 시작 - 전화번호 입력 + 동의
    같은 번호로 오늘 이미 참여한 경우 기존 세션 반환
    """
    # 요청 횟수 제한 (IP당 10분 30회, 번호당 1시간 10회)
    from app.security import rate_limiter, client_ip
    import re as _re
    ip = client_ip(req) if req else "unknown"
    digits = _re.sub(r"\D", "", request.phone or "")
    if not rate_limiter.allow(f"start:ip:{ip}", 30, 600) or \
            not rate_limiter.allow(f"start:phone:{digits}", 10, 3600):
        raise HTTPException(status_code=429, detail="요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")

    store = await get_store_by_code(store_code, db)
    store_settings = await get_store_settings(store.id, db)

    from ..services.otp import get_options, recently_verified
    if (await get_options(db, store.id)).phone_verify and not await recently_verified(db, request.phone):
        raise HTTPException(status_code=403, detail="휴대폰 인증을 먼저 해주세요")

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
        set_session_cookie(response, existing.id)
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
    set_session_cookie(response, session.id)

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

    event = request.event or request.event_type
    if event not in event_map:
        raise HTTPException(status_code=400, detail="유효하지 않은 이벤트입니다")

    assignment_service = AssignmentService(db)
    await assignment_service.update_session_status(session, event_map[event])
    await db.commit()

    return {"status": "ok", "event": event}


@router.post("/api/v1/session/{session_id}/text")
async def update_text(
    session_id: UUID,
    request: TextUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """손님이 직접 고친 문구 저장"""
    text = (request.text or "").strip()
    if not text or len(text) > 1000:
        raise HTTPException(status_code=400, detail="문구는 1~1000자로 입력해주세요")
    session = (await db.execute(select(ReviewSession).where(ReviewSession.id == session_id))).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")
    session.generated_text = text
    await db.commit()
    return {"status": "ok"}


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

    # 4자리 PIN 무작위 대입 방지: 세션당 10분에 5회
    from app.security import rate_limiter
    if not rate_limiter.allow(f"pin:{session_id}", 5, 600):
        raise HTTPException(status_code=429, detail="PIN 입력 횟수를 초과했습니다. 10분 후 다시 시도해주세요.")

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



# ============================================================
# 수신거부 (광고 문자 하단 안내 링크 → 이 화면)
# ============================================================

@router.post("/api/v1/consent/withdraw")
async def withdraw_consent(request: ConsentWithdrawRequest, req: Request, db: AsyncSession = Depends(get_db)):
    """매장 혜택 문자 수신거부 (해당 매장만)"""
    from app.security import rate_limiter, client_ip
    from ..models.customer import Customer, StoreCustomer
    from ..services.customers import hash_phone

    ip = client_ip(req)
    if not rate_limiter.allow(f"withdraw:{ip}", 20, 3600):
        raise HTTPException(status_code=429, detail="요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")

    store = await get_store_by_code(request.store_code, db)
    customer = (await db.execute(select(Customer).where(Customer.phone_hash == hash_phone(request.phone)))).scalar_one_or_none()
    # 등록 여부를 알려주지 않음 (번호 존재 여부 노출 방지) → 항상 같은 응답
    if customer:
        sc = (await db.execute(select(StoreCustomer).where(
            StoreCustomer.store_id == store.id, StoreCustomer.customer_id == customer.id))).scalar_one_or_none()
        if sc and sc.marketing_opt_in:
            sc.marketing_opt_in = False
            sc.opt_out_at = datetime.now(timezone.utc)
            await CustomerService(db).record_consent(
                customer.id, store.id, ConsentType.MARKETING, ConsentAction.WITHDRAW,
                ip=ip, user_agent=req.headers.get("user-agent"))
        await db.commit()
    return {"status": "ok", "message": f"{store.name}의 혜택 문자 수신이 거부되었습니다."}


@router.get("/optout/{store_code}", response_class=HTMLResponse)
async def optout_page(request: Request, store_code: str, db: AsyncSession = Depends(get_db)):
    """수신거부 화면"""
    store = await get_store_by_code(store_code, db)
    return templates.TemplateResponse(
        request=request, name="customer/optout.html",
        context={"store": {"name": store.name, "store_code": store.store_code, "naver_review_url": None},
                 "table_no": ""})



# ============================================================
# 휴대폰 인증번호 (Phase 9, 매장에서 켠 경우만)
# ============================================================

class OtpSendRequest(BaseModel):
    phone: str
    store_code: str


class OtpVerifyRequest(BaseModel):
    phone: str
    code: str


@router.post("/api/v1/otp/send")
async def otp_send(request: OtpSendRequest, req: Request, db: AsyncSession = Depends(get_db)):
    from app.security import rate_limiter, client_ip
    from ..services.otp import send_code
    digits = re.sub(r"\D", "", request.phone or "")
    if not re.fullmatch(r"01[016789]\d{7,8}", digits):
        raise HTTPException(status_code=422, detail="휴대폰 번호를 정확히 입력해주세요")
    if not rate_limiter.allow(f"otp:phone:{digits}", 3, 600) or \
            not rate_limiter.allow(f"otp:ip:{client_ip(req)}", 10, 600):
        raise HTTPException(status_code=429, detail="인증번호 요청이 너무 많습니다. 10분 후 다시 시도해주세요.")
    store = await get_store_by_code(request.store_code, db)
    try:
        dev_code = await send_code(db, digits, store.name)
    except RuntimeError as e:
        await db.rollback()
        raise HTTPException(status_code=503, detail=str(e))
    await db.commit()
    out = {"status": "sent", "expires_in": 180}
    if dev_code and get_settings().DEBUG:
        out["dev_code"] = dev_code
    return out


@router.post("/api/v1/otp/verify")
async def otp_verify(request: OtpVerifyRequest, db: AsyncSession = Depends(get_db)):
    from ..services.otp import verify_code
    ok = await verify_code(db, request.phone, request.code)
    await db.commit()
    if not ok:
        raise HTTPException(status_code=400, detail="인증번호가 맞지 않거나 만료되었습니다")
    return {"status": "verified"}
