"""세션 및 이벤트 모델"""
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from sqlalchemy import String, Integer, DateTime, Enum, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
import enum

from .base import Base, TimestampMixin


class SessionStatus(str, enum.Enum):
    STARTED = "started"
    ASSIGNED = "assigned"
    DOWNLOADED = "downloaded"
    REDIRECTED = "redirected"
    COMPLETED = "completed"
    BENEFIT_GIVEN = "benefit_given"
    EXPIRED = "expired"


class ReviewSession(Base):
    __tablename__ = "review_sessions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4
    )
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)

    table_no: Mapped[Optional[str]] = mapped_column(String(10))
    device_id: Mapped[Optional[str]] = mapped_column(String(100))

    receipt_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True))
    generated_text: Mapped[Optional[str]] = mapped_column(String(500))
    selected_keywords: Mapped[Optional[dict]] = mapped_column(JSON)
    regenerate_count: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus),
        default=SessionStatus.STARTED
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    downloaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    redirected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    benefit_given_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    completion_code: Mapped[Optional[str]] = mapped_column(String(6))


class TextHistory(Base):
    __tablename__ = "text_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventLog(Base, TimestampMixin):
    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
