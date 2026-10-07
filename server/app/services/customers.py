"""고객 서비스 - 생성, 암호화, 동의 관리"""
import re
import os
import hmac
import hashlib
import base64
from datetime import datetime, timezone
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.customer import Customer, StoreCustomer, ConsentLog, ConsentType, ConsentAction


def normalize_phone(phone: str) -> str:
    """전화번호 정규화 - 숫자만 추출"""
    return re.sub(r"[^0-9]", "", phone)


def hash_phone(phone: str) -> str:
    """HMAC-SHA256으로 전화번호 해시 (조회용)"""
    settings = get_settings()
    normalized = normalize_phone(phone)
    return hmac.new(
        settings.PHONE_HMAC_KEY.encode(),
        normalized.encode(),
        hashlib.sha256
    ).hexdigest()


def encrypt_phone(phone: str) -> str:
    """AES-GCM으로 전화번호 암호화"""
    settings = get_settings()
    key = settings.PHONE_ENC_KEY.encode()[:32].ljust(32, b'\0')
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    normalized = normalize_phone(phone)
    ciphertext = aesgcm.encrypt(nonce, normalized.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_phone(encrypted: str) -> str:
    """AES-GCM으로 전화번호 복호화"""
    settings = get_settings()
    key = settings.PHONE_ENC_KEY.encode()[:32].ljust(32, b'\0')
    aesgcm = AESGCM(key)
    data = base64.b64decode(encrypted)
    nonce, ciphertext = data[:12], data[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode()


def mask_phone(phone: str) -> str:
    """전화번호 마스킹 (010-****-1234)"""
    normalized = normalize_phone(phone)
    if len(normalized) == 11:
        return f"{normalized[:3]}-****-{normalized[-4:]}"
    elif len(normalized) == 10:
        return f"{normalized[:3]}-***-{normalized[-4:]}"
    return "***"


class CustomerService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_customer(self, phone: str) -> Customer:
        """전화번호로 고객 조회 또는 생성"""
        phone_hash = hash_phone(phone)

        result = await self.db.execute(
            select(Customer).where(Customer.phone_hash == phone_hash)
        )
        customer = result.scalar_one_or_none()

        if customer:
            return customer

        customer = Customer(
            phone_enc=encrypt_phone(phone),
            phone_hash=phone_hash
        )
        self.db.add(customer)
        await self.db.flush()
        return customer

    async def get_or_create_store_customer(
        self,
        store_id: int,
        customer_id: int,
        marketing_opt_in: bool = False
    ) -> StoreCustomer:
        """매장-고객 관계 조회 또는 생성"""
        now = datetime.now(timezone.utc)

        result = await self.db.execute(
            select(StoreCustomer).where(
                StoreCustomer.store_id == store_id,
                StoreCustomer.customer_id == customer_id
            )
        )
        store_customer = result.scalar_one_or_none()

        if store_customer:
            store_customer.last_visit_at = now
            store_customer.visit_count += 1

            if marketing_opt_in and not store_customer.marketing_opt_in:
                store_customer.marketing_opt_in = True
                store_customer.opt_in_at = now
            elif not marketing_opt_in and store_customer.marketing_opt_in:
                store_customer.marketing_opt_in = False
                store_customer.opt_out_at = now

            return store_customer

        store_customer = StoreCustomer(
            store_id=store_id,
            customer_id=customer_id,
            first_visit_at=now,
            last_visit_at=now,
            visit_count=1,
            marketing_opt_in=marketing_opt_in,
            opt_in_at=now if marketing_opt_in else None
        )
        self.db.add(store_customer)
        await self.db.flush()
        return store_customer

    async def record_consent(
        self,
        customer_id: int,
        store_id: int,
        consent_type: ConsentType,
        action: ConsentAction,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        terms_version: str = "1.0"
    ) -> ConsentLog:
        """동의 기록"""
        log = ConsentLog(
            customer_id=customer_id,
            store_id=store_id,
            consent_type=consent_type,
            action=action,
            terms_version=terms_version,
            ip=ip,
            user_agent=user_agent
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def check_today_participation(
        self,
        store_id: int,
        customer_id: int,
        business_day_start: datetime
    ) -> Optional["ReviewSession"]:
        """오늘 이미 참여했는지 확인"""
        from ..models.session import ReviewSession

        result = await self.db.execute(
            select(ReviewSession).where(
                ReviewSession.store_id == store_id,
                ReviewSession.customer_id == customer_id,
                ReviewSession.started_at >= business_day_start
            ).order_by(ReviewSession.started_at.desc())
        )
        return result.scalar_one_or_none()
