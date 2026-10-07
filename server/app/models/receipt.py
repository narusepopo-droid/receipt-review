"""영수증 모델"""
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from sqlalchemy import String, Integer, DateTime, Enum, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
import enum

from .base import Base, TimestampMixin


class ReceiptClassification(str, enum.Enum):
    NORMAL = "normal"
    UNCLASSIFIED = "unclassified"


class ReceiptStatus(str, enum.Enum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    DISPOSED = "disposed"


class Receipt(Base, TimestampMixin):
    __tablename__ = "receipts"
    __table_args__ = (
        UniqueConstraint("store_id", "approval_no", "paid_at", name="uq_receipt_unique"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4
    )
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)

    approval_no: Mapped[Optional[str]] = mapped_column(String(20))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Optional[int]] = mapped_column(Integer)
    card_issuer: Mapped[Optional[str]] = mapped_column(String(50))

    items: Mapped[Optional[dict]] = mapped_column(JSON)
    raw_text: Mapped[Optional[str]] = mapped_column(String)
    raw_bytes_path: Mapped[Optional[str]] = mapped_column(String(500))
    image_path: Mapped[Optional[str]] = mapped_column(String(500))

    classification: Mapped[ReceiptClassification] = mapped_column(
        Enum(ReceiptClassification),
        default=ReceiptClassification.NORMAL
    )
    status: Mapped[ReceiptStatus] = mapped_column(
        Enum(ReceiptStatus),
        default=ReceiptStatus.AVAILABLE
    )

    assigned_session_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True))
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    disposed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dispose_reason: Mapped[Optional[str]] = mapped_column(String(50))
