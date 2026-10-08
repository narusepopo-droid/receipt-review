"""
인증 라우터 - 점주 가입, 로그인, 결제
"""
import os
import secrets
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request, Header
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.store import Store, StoreSettings, StoreStatus
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


# ============ Pydantic Models ============

class SignupRequest(BaseModel):
    store_name: str
    owner_name: str
    phone: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    store_id: Optional[int] = None
    store_name: Optional[str] = None
    store_code: Optional[str] = None
    message: Optional[str] = None


class PaymentWebhook(BaseModel):
    paymentKey: str
    orderId: str
    amount: int
    status: str


# ============ 유틸리티 ============

from app.security import hash_password, verify_password  # noqa: E402  (bcrypt + 예전 방식 호환)

# 에이전트 토큰 유효기간. 하트비트마다 하루 지난 토큰은 새로 발급되므로 켜져 있는 포스는 만료되지 않음
TOKEN_MAX_AGE = timedelta(days=90)
TOKEN_REFRESH_AFTER = timedelta(days=1)


def generate_token(store_id: int) -> str:
    """인증 토큰 생성"""
    timestamp = int(datetime.now().timestamp())
    data = f"{store_id}:{timestamp}"
    signature = hmac.new(
        settings.SECRET_KEY.encode(),
        data.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    return f"{store_id}:{timestamp}:{signature}"


def verify_token(token: str) -> Optional[int]:
    """토큰 검증 → store_id 반환"""
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return None
        store_id, timestamp, signature = parts

        # 서명 검증
        data = f"{store_id}:{timestamp}"
        expected = hmac.new(
            settings.SECRET_KEY.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()[:16]

        if signature != expected:
            return None

        token_time = datetime.fromtimestamp(int(timestamp))
        if datetime.now() - token_time > TOKEN_MAX_AGE:
            return None

        return int(store_id)
    except (ValueError, TypeError):
        return None


def token_needs_refresh(token: str) -> bool:
    try:
        ts = int(token.split(":")[1])
        return datetime.now() - datetime.fromtimestamp(ts) > TOKEN_REFRESH_AFTER
    except (IndexError, ValueError):
        return False


def generate_store_code() -> str:
    """매장 코드 생성 (6자리 영숫자)"""
    return secrets.token_hex(3).upper()


# ============ 가입 페이지 ============

@router.get("/signup", response_class=HTMLResponse)
async def signup_page():
    """가입 신청 페이지"""
    html = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>가입 신청 - 영수증리뷰</title>
        <link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css" rel="stylesheet">
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                font-family: 'Pretendard', sans-serif;
                background: linear-gradient(135deg, #f5f7fa 0%, #e4e9f2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }
            .container {
                background: white;
                border-radius: 20px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.1);
                max-width: 480px;
                width: 100%;
                padding: 48px 40px;
            }
            .logo {
                text-align: center;
                margin-bottom: 32px;
            }
            .logo-icon {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 56px;
                height: 56px;
                background: #03C75A;
                border-radius: 14px;
                margin-bottom: 12px;
            }
            .logo-icon span {
                color: white;
                font-size: 24px;
                font-weight: 700;
            }
            .logo-text {
                font-size: 24px;
                font-weight: 700;
                color: #1a1a1a;
            }
            .tabs {
                display: flex;
                margin-bottom: 24px;
                background: #f5f5f5;
                border-radius: 12px;
                padding: 4px;
            }
            .tab {
                flex: 1;
                padding: 12px;
                text-align: center;
                border-radius: 10px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s;
                border: none;
                background: none;
                font-size: 15px;
            }
            .tab.active {
                background: #03C75A;
                color: white;
            }
            .tab:not(.active) {
                color: #666;
            }
            .error-box {
                background: #fef2f2;
                border: 1px solid #fecaca;
                color: #dc2626;
                padding: 12px 16px;
                border-radius: 10px;
                margin-bottom: 20px;
                font-size: 14px;
                display: none;
            }
            .success-box {
                background: #f0fdf4;
                border: 1px solid #bbf7d0;
                color: #16a34a;
                padding: 12px 16px;
                border-radius: 10px;
                margin-bottom: 20px;
                font-size: 14px;
                display: none;
            }
            .form-title {
                font-size: 20px;
                font-weight: 700;
                margin-bottom: 8px;
                text-align: center;
            }
            .form-subtitle {
                color: #666;
                font-size: 14px;
                text-align: center;
                margin-bottom: 28px;
            }
            .input-group {
                margin-bottom: 20px;
            }
            .input-group label {
                display: block;
                font-size: 14px;
                font-weight: 600;
                margin-bottom: 8px;
                color: #333;
            }
            .input-group label span {
                color: #dc2626;
            }
            .input-group input {
                width: 100%;
                padding: 14px 16px;
                border: 2px solid #e5e5e5;
                border-radius: 12px;
                font-size: 15px;
                transition: all 0.2s;
            }
            .input-group input:focus {
                outline: none;
                border-color: #03C75A;
            }
            .btn {
                width: 100%;
                padding: 16px;
                background: #03C75A;
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s;
            }
            .btn:hover {
                background: #02a84d;
            }
            .btn:disabled {
                background: #ccc;
                cursor: not-allowed;
            }
            #signup-form, #login-form { display: none; }
            #signup-form.active, #login-form.active { display: block; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <div class="logo-icon"><span>N</span></div>
                <div class="logo-text">영수증리뷰</div>
            </div>

            <div class="tabs">
                <button class="tab active" onclick="showTab('signup')">가입하기</button>
                <button class="tab" onclick="showTab('login')">로그인</button>
            </div>

            <div class="error-box" id="error-box"></div>
            <div class="success-box" id="success-box"></div>

            <!-- 가입 폼 -->
            <form id="signup-form" class="active" onsubmit="submitSignup(event)">
                <h2 class="form-title">서비스 가입 신청</h2>
                <p class="form-subtitle">가입 신청 후 담당자 승인이 필요합니다</p>

                <div class="input-group">
                    <label>매장명 <span>*</span></label>
                    <input type="text" name="store_name" required placeholder="예: 맛있는 식당">
                </div>

                <div class="input-group">
                    <label>대표자명 <span>*</span></label>
                    <input type="text" name="owner_name" required placeholder="예: 홍길동">
                </div>

                <div class="input-group">
                    <label>연락처 <span>*</span></label>
                    <input type="tel" name="phone" required placeholder="010-0000-0000">
                </div>

                <div class="input-group">
                    <label>이메일 (로그인 ID) <span>*</span></label>
                    <input type="email" name="email" required placeholder="email@example.com">
                </div>

                <div class="input-group">
                    <label>비밀번호 <span>*</span></label>
                    <input type="password" name="password" required placeholder="비밀번호 입력">
                </div>

                <button type="submit" class="btn">가입 신청</button>
            </form>

            <!-- 로그인 폼 -->
            <form id="login-form" onsubmit="submitLogin(event)">
                <h2 class="form-title">로그인</h2>
                <p class="form-subtitle">가입 시 등록한 이메일로 로그인하세요</p>

                <div class="input-group">
                    <label>이메일 <span>*</span></label>
                    <input type="email" name="email" required placeholder="email@example.com">
                </div>

                <div class="input-group">
                    <label>비밀번호 <span>*</span></label>
                    <input type="password" name="password" required placeholder="비밀번호 입력">
                </div>

                <button type="submit" class="btn">로그인</button>
            </form>
        </div>

        <script>
            function showTab(tab) {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('form').forEach(f => f.classList.remove('active'));
                event.target.classList.add('active');
                document.getElementById(tab + '-form').classList.add('active');
                hideMessages();
            }

            function showError(msg) {
                const box = document.getElementById('error-box');
                box.textContent = msg;
                box.style.display = 'block';
                document.getElementById('success-box').style.display = 'none';
            }

            function showSuccess(msg) {
                const box = document.getElementById('success-box');
                box.textContent = msg;
                box.style.display = 'block';
                document.getElementById('error-box').style.display = 'none';
            }

            function hideMessages() {
                document.getElementById('error-box').style.display = 'none';
                document.getElementById('success-box').style.display = 'none';
            }

            async function submitSignup(e) {
                e.preventDefault();
                const form = e.target;
                const btn = form.querySelector('button');
                btn.disabled = true;
                btn.textContent = '처리 중...';
                hideMessages();

                try {
                    const data = {
                        store_name: form.store_name.value,
                        owner_name: form.owner_name.value,
                        phone: form.phone.value,
                        email: form.email.value,
                        password: form.password.value
                    };

                    const res = await fetch('/auth/signup', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });

                    const result = await res.json();

                    if (res.ok && result.success) {
                        showSuccess(result.message || '가입 신청 완료! 담당자 승인 후 로그인 가능합니다.');
                        form.reset();
                    } else {
                        showError(result.detail || result.message || '가입 신청에 실패했습니다.');
                    }
                } catch (err) {
                    showError('서버 연결에 실패했습니다. 잠시 후 다시 시도해주세요.');
                }

                btn.disabled = false;
                btn.textContent = '가입 신청';
            }

            async function submitLogin(e) {
                e.preventDefault();
                const form = e.target;
                const btn = form.querySelector('button');
                btn.disabled = true;
                btn.textContent = '로그인 중...';
                hideMessages();

                try {
                    const data = {
                        email: form.email.value,
                        password: form.password.value
                    };

                    const res = await fetch('/auth/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });

                    const result = await res.json();

                    if (result.success) {
                        window.location.href = '/download';
                    } else {
                        showError(result.message || '로그인에 실패했습니다.');
                    }
                } catch (err) {
                    showError('서버 연결에 실패했습니다.');
                }

                btn.disabled = false;
                btn.textContent = '로그인';
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(html)


# ============ API 엔드포인트 ============

@router.post("/signup")
async def signup(req: SignupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """
    점주 회원가입 (결제 전 - pending 상태)
    결제 완료 후 active로 변경됨
    """
    from app.security import rate_limiter, client_ip
    if not rate_limiter.allow(f"signup:{client_ip(request)}", 10, 3600):
        raise HTTPException(status_code=429, detail="가입 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
    # 이메일 중복 체크
    existing = await db.execute(
        select(Store).where(Store.admin_login_id == req.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "이미 가입된 이메일입니다")

    # 매장 코드 생성 (중복 방지)
    while True:
        store_code = generate_store_code()
        check = await db.execute(
            select(Store).where(Store.store_code == store_code)
        )
        if not check.scalar_one_or_none():
            break

    # 매장 생성 (결제 대기 상태)
    store = Store(
        name=req.store_name,
        store_code=store_code,
        admin_login_id=req.email,
        admin_password_hash=hash_password(req.password),
        status=StoreStatus.PAUSED,  # 결제 전까지 비활성
    )
    db.add(store)
    await db.flush()

    # 기본 설정 생성
    store_settings = StoreSettings(
        store_id=store.id,
        benefit_text="리뷰 작성 시 서비스 증정",
        keywords=[
            {"label": "맛있어요", "default": True},
            {"label": "친절해요", "default": True},
            {"label": "깔끔해요", "default": False},
        ],
        signature_menus=["대표메뉴"],
        templates=[
            "{메뉴} 정말 맛있었어요! {키워드1} 다음에 또 올게요.",
            "오늘 {메뉴} 먹었는데 {키워드1} {키워드2} 추천합니다.",
        ]
    )
    db.add(store_settings)
    await db.commit()

    # 가입 완료 (승인 대기 상태)
    return {
        "success": True,
        "store_id": store.id,
        "store_code": store_code,
        "message": "가입 신청 완료! 담당자 확인 후 승인됩니다. 승인되면 로그인 가능합니다."
    }


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """점주 로그인 (에이전트/웹 공용, 5회 실패 시 10분 잠금)"""
    from app.security import login_limiter, client_ip
    key = login_limiter.key("auth", client_ip(request), req.email)
    left = login_limiter.remaining_lock(key)
    if left:
        return LoginResponse(success=False, message=f"로그인 시도가 너무 많습니다. {left // 60 + 1}분 후 다시 시도하세요.")

    result = await db.execute(
        select(Store).where(Store.admin_login_id == req.email)
    )
    store = result.scalar_one_or_none()

    if not store or not verify_password(req.password, store.admin_password_hash):
        login_limiter.fail(key)
        return LoginResponse(success=False, message="이메일 또는 비밀번호가 올바르지 않습니다")
    login_limiter.success(key)

    if store.status == StoreStatus.PAUSED:
        return LoginResponse(success=False, message="승인 대기 중입니다. 담당자 승인 후 로그인 가능합니다.")

    token = generate_token(store.id)

    return LoginResponse(
        success=True,
        token=token,
        store_id=store.id,
        store_name=store.name,
        store_code=store.store_code
    )


@router.get("/payment/{store_id}", response_class=HTMLResponse)
async def payment_page(store_id: int, db: AsyncSession = Depends(get_db)):
    """결제 페이지"""
    result = await db.execute(
        select(Store).where(Store.id == store_id)
    )
    store = result.scalar_one_or_none()

    if not store:
        raise HTTPException(404, "매장을 찾을 수 없습니다")

    # 토스페이먼츠 결제 위젯 페이지
    # TODO: 실제 토스페이먼츠 클라이언트 키로 교체
    html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>결제 - 영수증리뷰</title>
        <script src="https://js.tosspayments.com/v1/payment-widget"></script>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: 'Noto Sans KR', sans-serif;
                background: #f5f5f5;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            .container {{
                background: white;
                border-radius: 16px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.1);
                max-width: 480px;
                width: 100%;
                padding: 40px;
            }}
            h1 {{ font-size: 24px; margin-bottom: 8px; text-align: center; }}
            .subtitle {{ color: #666; text-align: center; margin-bottom: 32px; }}
            .info {{ background: #f8f9fa; padding: 20px; border-radius: 12px; margin-bottom: 24px; }}
            .info-row {{ display: flex; justify-content: space-between; margin-bottom: 8px; }}
            .info-row:last-child {{ margin-bottom: 0; }}
            .info-label {{ color: #666; }}
            .info-value {{ font-weight: 600; }}
            .price {{ font-size: 28px; font-weight: 700; color: #03C75A; text-align: center; margin: 24px 0; }}
            #payment-widget {{ margin: 24px 0; }}
            .btn {{
                width: 100%;
                padding: 16px;
                background: #03C75A;
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
            }}
            .btn:hover {{ background: #02a84d; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>영수증리뷰 결제</h1>
            <p class="subtitle">결제 완료 후 바로 사용 가능합니다</p>

            <div class="info">
                <div class="info-row">
                    <span class="info-label">매장명</span>
                    <span class="info-value">{store.name}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">상품</span>
                    <span class="info-value">영수증리뷰 월 구독</span>
                </div>
            </div>

            <div class="price">월 33,000원</div>

            <div id="payment-widget"></div>

            <button class="btn" onclick="requestPayment()">결제하기</button>
        </div>

        <script>
            // TODO: 실제 클라이언트 키로 교체
            const clientKey = "test_ck_D5GePWvyJnrK0W0k6q8gLzN97Eoq";
            const customerKey = "store_{store.id}";

            const paymentWidget = PaymentWidget(clientKey, customerKey);

            paymentWidget.renderPaymentMethods(
                "#payment-widget",
                {{ value: 33000 }},
                {{ variantKey: "DEFAULT" }}
            );

            async function requestPayment() {{
                try {{
                    await paymentWidget.requestPayment({{
                        orderId: "order_{store.id}_" + Date.now(),
                        orderName: "영수증리뷰 월 구독",
                        successUrl: window.location.origin + "/auth/payment/success",
                        failUrl: window.location.origin + "/auth/payment/fail",
                        customerEmail: "{store.admin_login_id}",
                        customerName: "{store.name}",
                    }});
                }} catch (error) {{
                    console.error(error);
                }}
            }}
        </script>
    </body>
    </html>
    """
    return html


@router.get("/payment/success")
async def payment_success(
    paymentKey: str,
    orderId: str,
    amount: int,
    db: AsyncSession = Depends(get_db)
):
    """결제 성공 콜백"""
    # orderId에서 store_id 추출
    try:
        store_id = int(orderId.split("_")[1])
    except:
        raise HTTPException(400, "잘못된 주문 ID")

    # TODO: 토스페이먼츠 API로 결제 승인 요청
    # 실제로는 서버에서 결제 승인을 해야 함

    # 매장 활성화
    result = await db.execute(
        select(Store).where(Store.id == store_id)
    )
    store = result.scalar_one_or_none()

    if store:
        store.status = StoreStatus.ACTIVE
        await db.commit()

    # 성공 페이지로 리다이렉트
    html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>결제 완료 - 영수증리뷰</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: 'Noto Sans KR', sans-serif;
                background: #f5f5f5;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            .container {{
                background: white;
                border-radius: 16px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.1);
                max-width: 480px;
                width: 100%;
                padding: 40px;
                text-align: center;
            }}
            .check {{ font-size: 64px; margin-bottom: 24px; }}
            h1 {{ font-size: 24px; margin-bottom: 8px; color: #03C75A; }}
            .subtitle {{ color: #666; margin-bottom: 32px; }}
            .btn {{
                display: inline-block;
                padding: 16px 32px;
                background: #03C75A;
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 16px;
                font-weight: 600;
                text-decoration: none;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="check">✅</div>
            <h1>결제 완료!</h1>
            <p class="subtitle">이제 프로그램을 다운로드하고 설치하세요</p>
            <a href="/download" class="btn">프로그램 다운로드</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


@router.get("/payment/fail")
async def payment_fail(code: str = "", message: str = ""):
    """결제 실패 콜백"""
    html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>결제 실패 - 영수증리뷰</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: 'Noto Sans KR', sans-serif;
                background: #f5f5f5;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            .container {{
                background: white;
                border-radius: 16px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.1);
                max-width: 480px;
                width: 100%;
                padding: 40px;
                text-align: center;
            }}
            .icon {{ font-size: 64px; margin-bottom: 24px; }}
            h1 {{ font-size: 24px; margin-bottom: 8px; color: #dc2626; }}
            .message {{ color: #666; margin-bottom: 32px; }}
            .btn {{
                display: inline-block;
                padding: 16px 32px;
                background: #333;
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 16px;
                font-weight: 600;
                text-decoration: none;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">❌</div>
            <h1>결제 실패</h1>
            <p class="message">{message or "결제 중 오류가 발생했습니다"}</p>
            <a href="javascript:history.back()" class="btn">다시 시도</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


@router.get("/verify")
async def verify_auth(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """토큰 검증 (에이전트용)"""
    if not authorization:
        raise HTTPException(401, "인증 토큰이 없습니다")

    token = authorization.replace("Bearer ", "")
    store_id = verify_token(token)

    if not store_id:
        raise HTTPException(401, "유효하지 않은 토큰입니다")

    result = await db.execute(
        select(Store).where(Store.id == store_id)
    )
    store = result.scalar_one_or_none()

    if not store:
        raise HTTPException(404, "매장을 찾을 수 없습니다")

    if store.status != StoreStatus.ACTIVE:
        raise HTTPException(403, "비활성화된 계정입니다")

    return {
        "valid": True,
        "store_id": store.id,
        "store_name": store.name,
        "store_code": store.store_code
    }
