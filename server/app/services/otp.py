"""
휴대폰 인증번호 (Phase 9, 매장별 선택)
- 6자리, 3분 유효, 5회 틀리면 무효
- 번호·코드는 해시로만 저장
- 문자는 알리고로 발송 (키 없으면 모의 → 서버 로그에만 남음, DEBUG 에서만 응답에 포함)
"""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.options import PhoneOtp, StoreOptions
from app.services.customers import hash_phone, normalize_phone

logger = logging.getLogger(__name__)
OTP_TTL = timedelta(minutes=3)
MAX_ATTEMPTS = 5
VERIFIED_VALID = timedelta(minutes=10)   # 인증 후 10분 안에 참여 시작


def _code_hash(phone_hash: str, code: str) -> str:
    return hmac.new(get_settings().SECRET_KEY.encode(), f"{phone_hash}:{code}".encode(), hashlib.sha256).hexdigest()


async def get_options(db: AsyncSession, store_id: int) -> StoreOptions:
    o = (await db.execute(select(StoreOptions).where(StoreOptions.store_id == store_id))).scalar_one_or_none()
    return o or StoreOptions(store_id=store_id, phone_verify=False, ai_text=False, review_check=False)


async def send_code(db: AsyncSession, phone: str, store_name: str) -> Optional[str]:
    """인증번호 발송. 모의 발송이면 코드를 반환 (DEBUG 응답용)"""
    from app.services.sms import is_test_mode, _aligo_send
    ph = hash_phone(phone)
    code = f"{secrets.randbelow(1000000):06d}"
    db.add(PhoneOtp(phone_hash=ph, code_hash=_code_hash(ph, code),
                    expires_at=datetime.now(timezone.utc) + OTP_TTL))
    await db.flush()
    text = f"[{store_name}] 리뷰 이벤트 인증번호 {code} (3분 안에 입력)"
    if is_test_mode():
        logger.warning("OTP 모의 발송 (알리고 키 없음): ***-%s %s", normalize_phone(phone)[-4:], code)
        return code
    ok, _, msg = await _aligo_send([normalize_phone(phone)], text, "SMS", "")
    if not ok:
        raise RuntimeError(f"인증번호 문자 발송 실패: {msg}")
    return None


async def verify_code(db: AsyncSession, phone: str, code: str) -> bool:
    ph = hash_phone(phone)
    now = datetime.now(timezone.utc)
    otp = (await db.execute(select(PhoneOtp).where(PhoneOtp.phone_hash == ph)
                            .order_by(PhoneOtp.id.desc()).limit(1))).scalar_one_or_none()
    if not otp or otp.verified_at:
        return False
    exp = otp.expires_at if otp.expires_at.tzinfo else otp.expires_at.replace(tzinfo=timezone.utc)
    if exp < now or otp.attempts >= MAX_ATTEMPTS:
        return False
    otp.attempts += 1
    if hmac.compare_digest(otp.code_hash, _code_hash(ph, (code or "").strip())):
        otp.verified_at = now
        return True
    return False


async def recently_verified(db: AsyncSession, phone: str) -> bool:
    ph = hash_phone(phone)
    otp = (await db.execute(select(PhoneOtp).where(PhoneOtp.phone_hash == ph, PhoneOtp.verified_at.isnot(None))
                            .order_by(PhoneOtp.id.desc()).limit(1))).scalar_one_or_none()
    if not otp:
        return False
    v = otp.verified_at if otp.verified_at.tzinfo else otp.verified_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - v < VERIFIED_VALID
