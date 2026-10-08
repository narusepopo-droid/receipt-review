"""
홍보 문자 발송 (Phase 8, 알리고)

규칙 (정보통신망법 광고성 정보 전송 기준)
- 수신동의(marketing_opt_in) 고객에게만 발송 — 시스템적으로 그 외 번호는 대상이 될 수 없음
- 문구 맨 앞 "(광고)매장명", 맨 끝 무료 수신거부 안내 자동 삽입
- 야간(21:00~08:00) 발송 금지 — 별도 야간 동의를 받지 않으므로 예약도 거부
- 원본 번호는 화면·파일로 나가지 않음 (발송 직전 서버에서만 복호화)

ALIGO_KEY / ALIGO_USER_ID / ALIGO_SENDER 가 없으면 '모의 발송' (실제 전송 없이 대상·비용만 기록)
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.customer import Customer, StoreCustomer
from app.models.sms import SmsCampaign, SmsStatus, SmsWallet, SmsWalletLog
from app.models.store import Store
from app.services.customers import decrypt_phone

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
NIGHT_START, NIGHT_END = 21, 8           # 21:00 ~ 다음날 08:00 발송 금지
SMS_MAX_BYTES = 90                        # 넘으면 LMS
LMS_MAX_BYTES = 2000
ALIGO_URL = "https://apis.aligo.in/send/"
ALIGO_BATCH = 1000


class SmsError(Exception):
    pass


def text_bytes(text: str) -> int:
    """문자 길이 (EUC-KR 기준: 한글 2바이트)"""
    return len(text.encode("cp949", errors="replace"))


def compose(store: Store, body: str) -> tuple[str, str]:
    """(최종 문구, SMS/LMS)"""
    s = get_settings()
    optout_url = f"{s.SERVER_URL}/optout/{store.store_code}"
    lines = [f"(광고){store.name}", body.strip(), ""]
    if s.ALIGO_OPTOUT_080:
        lines.append(f"무료수신거부 {s.ALIGO_OPTOUT_080}")
    lines.append(f"수신거부 {optout_url}")
    final = "\n".join(lines)
    return final, ("SMS" if text_bytes(final) <= SMS_MAX_BYTES else "LMS")


def unit_cost(msg_type: str) -> int:
    s = get_settings()
    return s.SMS_COST_LMS if msg_type == "LMS" else s.SMS_COST_SMS


def is_night(dt: datetime) -> bool:
    h = dt.astimezone(KST).hour
    return h >= NIGHT_START or h < NIGHT_END


def is_test_mode() -> bool:
    s = get_settings()
    return not (s.ALIGO_KEY and s.ALIGO_USER_ID and s.ALIGO_SENDER)


async def opted_in_customers(db: AsyncSession, store_id: int) -> list[Customer]:
    return (await db.execute(
        select(Customer).join(StoreCustomer, StoreCustomer.customer_id == Customer.id)
        .where(StoreCustomer.store_id == store_id, StoreCustomer.marketing_opt_in.is_(True))
    )).scalars().all()


async def get_wallet(db: AsyncSession, store_id: int) -> SmsWallet:
    w = (await db.execute(select(SmsWallet).where(SmsWallet.store_id == store_id))).scalar_one_or_none()
    if not w:
        w = SmsWallet(store_id=store_id, balance=0)
        db.add(w)
        await db.flush()
    return w


async def charge(db: AsyncSession, store_id: int, amount: int, reason: str) -> int:
    w = await get_wallet(db, store_id)
    w.balance += amount
    db.add(SmsWalletLog(store_id=store_id, amount=amount, reason=reason))
    await db.flush()
    return w.balance


async def create_campaign(db: AsyncSession, store: Store, body: str,
                          scheduled_at: Optional[datetime] = None) -> SmsCampaign:
    """발송 예약 (즉시 발송도 '지금'으로 예약 후 스케줄러/즉시 처리)"""
    body = (body or "").strip()
    if not body:
        raise SmsError("문자 내용을 입력해주세요")
    final, msg_type = compose(store, body)
    if text_bytes(final) > LMS_MAX_BYTES:
        raise SmsError(f"문자가 너무 깁니다 ({text_bytes(final)}바이트 / 최대 {LMS_MAX_BYTES})")

    now = datetime.now(timezone.utc)
    when = scheduled_at or now
    if when.tzinfo is None:
        when = when.replace(tzinfo=KST)
    if when < now - timedelta(minutes=1):
        raise SmsError("지난 시각으로는 예약할 수 없습니다")
    if is_night(when):
        raise SmsError("야간(21시~08시)에는 광고 문자를 보낼 수 없습니다")

    targets = await opted_in_customers(db, store.id)
    if not targets:
        raise SmsError("문자 수신에 동의한 고객이 없습니다")
    cost = unit_cost(msg_type) * len(targets)
    wallet = await get_wallet(db, store.id)
    test_mode = is_test_mode()
    if not test_mode and wallet.balance < cost:
        raise SmsError(f"잔액이 부족합니다 (필요 {cost:,}원 / 잔액 {wallet.balance:,}원)")

    c = SmsCampaign(store_id=store.id, body=body, final_text=final, msg_type=msg_type,
                    scheduled_at=when, status=SmsStatus.SCHEDULED, target_count=len(targets),
                    cost=cost, test_mode=test_mode)
    db.add(c)
    await db.flush()
    return c


async def _aligo_send(numbers: list[str], text: str, msg_type: str, title: str) -> tuple[int, int, str]:
    s = get_settings()
    ok = fail = 0
    msgs = []
    async with httpx.AsyncClient(timeout=30) as client:
        for i in range(0, len(numbers), ALIGO_BATCH):
            batch = numbers[i:i + ALIGO_BATCH]
            data = {"key": s.ALIGO_KEY, "user_id": s.ALIGO_USER_ID, "sender": s.ALIGO_SENDER,
                    "receiver": ",".join(batch), "msg": text, "msg_type": msg_type}
            if msg_type == "LMS":
                data["title"] = title[:44]
            r = await client.post(ALIGO_URL, data=data)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if str(body.get("result_code")) == "1":
                ok += int(body.get("success_cnt", len(batch)))
                fail += int(body.get("error_cnt", 0))
            else:
                fail += len(batch)
            msgs.append(str(body.get("message", r.status_code)))
    return ok, fail, "; ".join(msgs)[:500]


async def send_campaign(db: AsyncSession, campaign: SmsCampaign) -> SmsCampaign:
    if campaign.status != SmsStatus.SCHEDULED:
        return campaign
    now = datetime.now(timezone.utc)
    if is_night(now):
        campaign.status = SmsStatus.FAILED
        campaign.result_message = "야간 시간대라 발송하지 않음"
        return campaign

    store = (await db.execute(select(Store).where(Store.id == campaign.store_id))).scalar_one()
    # 발송 시점 기준으로 다시 수신동의 고객 조회 (그 사이 수신거부한 사람 제외)
    numbers = []
    for c in await opted_in_customers(db, store.id):
        try:
            numbers.append(decrypt_phone(c.phone_enc))
        except Exception:
            logger.warning("phone decrypt failed for customer %s", c.id)
    campaign.status = SmsStatus.SENDING
    await db.flush()

    if not numbers:
        campaign.status = SmsStatus.FAILED
        campaign.result_message = "수신동의 고객 없음"
        return campaign

    if campaign.test_mode or is_test_mode():
        ok, fail, msg = len(numbers), 0, "모의 발송 (알리고 키 미설정 - 실제로 보내지 않음)"
    else:
        try:
            ok, fail, msg = await _aligo_send(numbers, campaign.final_text, campaign.msg_type, f"{store.name} 소식")
        except Exception as e:
            ok, fail, msg = 0, len(numbers), f"발송 오류: {e}"

    campaign.success_count, campaign.fail_count = ok, fail
    campaign.target_count = len(numbers)
    campaign.cost = unit_cost(campaign.msg_type) * ok
    campaign.sent_at = datetime.now(timezone.utc)
    campaign.status = SmsStatus.SENT if ok else SmsStatus.FAILED
    campaign.result_message = msg
    if ok and not campaign.test_mode:
        w = await get_wallet(db, store.id)
        w.balance -= campaign.cost
        db.add(SmsWalletLog(store_id=store.id, amount=-campaign.cost, reason=f"문자 발송 {ok}건", campaign_id=campaign.id))
    return campaign


async def run_due_campaigns(db: AsyncSession) -> int:
    """스케줄러: 예약 시각이 된 문자 발송"""
    due = (await db.execute(select(SmsCampaign).where(
        SmsCampaign.status == SmsStatus.SCHEDULED,
        SmsCampaign.scheduled_at <= datetime.now(timezone.utc)))).scalars().all()
    for c in due:
        await send_campaign(db, c)
        await db.commit()
    return len(due)
