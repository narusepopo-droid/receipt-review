"""고객 관련 모델"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Boolean, DateTime, Enum, ForeignKey, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column
import enum

from .base import Base, TimestampMixin


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone_enc: Mapped[str] = mapped_column(String(200), nullable=False)
    phone_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


class StoreCustomer(Base):
    __tablename__ = "store_customers"
    __table_args__ = (
        PrimaryKeyConstraint("store_id", "customer_id"),
    )

    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))

    first_visit_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    last_visit_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    visit_count: Mapped[int] = mapped_column(Integer, default=1)

    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    opt_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    opt_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ConsentType(str, enum.Enum):
    REQUIRED_PRIVACY = "required_privacy"
    MARKETING = "marketing"


class ConsentAction(str, enum.Enum):
    AGREE = "agree"
    WITHDRAW = "withdraw"


class ConsentLog(Base, TimestampMixin):
    __tablename__ = "consent_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)

    consent_type: Mapped[ConsentType] = mapped_column(Enum(ConsentType), nullable=False)
    action: Mapped[ConsentAction] = mapped_column(Enum(ConsentAction), nullable=False)
    terms_version: Mapped[Optional[str]] = mapped_column(String(20))

    ip: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
