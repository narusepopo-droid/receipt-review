"""홍보 문자 (Phase 8) - 수신동의 고객에게만, 시스템 안에서만 발송"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class SmsStatus(str, enum.Enum):
    SCHEDULED = "scheduled"   # 예약됨
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SmsCampaign(Base, TimestampMixin):
    __tablename__ = "sms_campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)          # 점주가 쓴 본문
    final_text: Mapped[str] = mapped_column(Text, nullable=False)    # (광고)·수신거부 포함 실제 발송 문구
    msg_type: Mapped[str] = mapped_column(String(3), nullable=False)  # SMS / LMS
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[SmsStatus] = mapped_column(Enum(SmsStatus), default=SmsStatus.SCHEDULED)
    target_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[int] = mapped_column(Integer, default=0)            # 원
    test_mode: Mapped[bool] = mapped_column(default=False)           # 모의 발송 (알리고 키 없음)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    result_message: Mapped[Optional[str]] = mapped_column(String(500))


class SmsWallet(Base):
    """매장 문자 충전 잔액 (운영자가 충전)"""
    __tablename__ = "sms_wallets"

    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)   # 원


class SmsWalletLog(Base, TimestampMixin):
    __tablename__ = "sms_wallet_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)   # +충전 / -사용
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    campaign_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sms_campaigns.id"))
