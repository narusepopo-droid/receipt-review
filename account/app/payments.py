"""
토스페이먼츠 (키가 없으면 결제 비활성 → 운영자 승인 흐름)

일시불: 결제창(requestPayment) → successUrl(paymentKey, orderId, amount) → confirm
자동결제: 카드 등록(requestBillingAuth) → successUrl(customerKey, authKey) → 빌링키 발급 → 매월 청구
인증: Authorization: Basic base64(시크릿키 + ":")
빌링키는 카드에 준하는 비밀 → 암호화 보관, 로그 금지
"""
import base64
import hashlib

import httpx
from cryptography.fernet import Fernet

from app.config import settings

API = "https://api.tosspayments.com"


class TossError(Exception):
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def _headers(idempotency_key: str = "") -> dict:
    token = base64.b64encode(f"{settings.TOSS_SECRET_KEY}:".encode()).decode()
    h = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    if idempotency_key:
        h["Idempotency-Key"] = idempotency_key
    return h


async def _post(path: str, body: dict, idem: str = "") -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(API + path, json=body, headers=_headers(idem))
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise TossError(data.get("message", f"결제 오류 ({r.status_code})"), data.get("code", ""))
    return data


async def confirm_payment(payment_key: str, order_id: str, amount: int) -> dict:
    return await _post("/v1/payments/confirm", {"paymentKey": payment_key, "orderId": order_id, "amount": amount},
                       idem=f"confirm-{order_id}")


async def cancel_payment(payment_key: str, reason: str, amount: int = None) -> dict:
    body = {"cancelReason": reason}
    if amount:
        body["cancelAmount"] = amount
    return await _post(f"/v1/payments/{payment_key}/cancel", body, idem=f"cancel-{payment_key}-{amount or 'all'}")


async def issue_billing_key(auth_key: str, customer_key: str) -> dict:
    return await _post("/v1/billing/authorizations/issue", {"authKey": auth_key, "customerKey": customer_key})


async def charge_billing(billing_key: str, customer_key: str, amount: int, order_id: str, order_name: str) -> dict:
    return await _post(f"/v1/billing/{billing_key}",
                       {"customerKey": customer_key, "amount": amount, "orderId": order_id, "orderName": order_name},
                       idem=f"charge-{order_id}")


# ───────────── 빌링키 암호화 ─────────────

def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(("billing:" + settings.SECRET_KEY).encode()).digest())
    return Fernet(key)


def encrypt(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode()


def decrypt(s: str) -> str:
    return _fernet().decrypt(s.encode()).decode()
