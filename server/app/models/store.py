"""매장 관련 모델"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, Enum, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum
import bcrypt

from .base import Base, TimestampMixin


class StoreStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"


class Store(Base, TimestampMixin):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    biz_no: Mapped[Optional[str]] = mapped_column(String(12))
    store_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)

    naver_review_url: Mapped[Optional[str]] = mapped_column(String(500))
    paper_width: Mapped[int] = mapped_column(Integer, default=576)
    status: Mapped[StoreStatus] = mapped_column(
        Enum(StoreStatus),
        default=StoreStatus.ACTIVE
    )

    admin_login_id: Mapped[Optional[str]] = mapped_column(String(50))
    admin_password_hash: Mapped[Optional[str]] = mapped_column(String(128))
    staff_pin: Mapped[Optional[str]] = mapped_column(String(4))

    settings: Mapped[Optional["StoreSettings"]] = relationship(
        back_populates="store",
        uselist=False
    )
    agents: Mapped[list["Agent"]] = relationship(back_populates="store")

    def set_password(self, password: str):
        """비밀번호 해시 저장 (bcrypt)"""
        from app.security import hash_password
        self.admin_password_hash = hash_password(password)

    def verify_password(self, password: str) -> bool:
        """비밀번호 검증 (bcrypt / 예전 가입 방식 모두)"""
        from app.security import verify_password
        return verify_password(password, self.admin_password_hash or "")


class StoreSettings(Base):
    __tablename__ = "store_settings"

    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id"),
        primary_key=True
    )

    keywords: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    signature_menus: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    templates: Mapped[Optional[dict]] = mapped_column(JSON, default=list)

    text_min_len: Mapped[int] = mapped_column(Integer, default=30)
    text_max_len: Mapped[int] = mapped_column(Integer, default=150)
    benefit_text: Mapped[Optional[str]] = mapped_column(String(200))
    primary_color: Mapped[Optional[str]] = mapped_column(String(7), default="#03C75A")

    assignment_policy: Mapped[str] = mapped_column(
        String(30),
        default="latest_same_day"
    )
    retention: Mapped[str] = mapped_column(String(30), default="end_of_day")
    business_day_cutoff: Mapped[str] = mapped_column(String(5), default="05:00")

    daily_assign_limit: Mapped[Optional[int]] = mapped_column(Integer)
    hourly_assign_limit: Mapped[Optional[int]] = mapped_column(Integer)

    store: Mapped["Store"] = relationship(back_populates="settings")


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)

    agent_key_hash: Mapped[Optional[str]] = mapped_column(String(128))
    activation_code: Mapped[Optional[str]] = mapped_column(String(8))
    activation_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    version: Mapped[Optional[str]] = mapped_column(String(20))
    capture_mode: Mapped[Optional[str]] = mapped_column(String(20))

    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_capture_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    queue_length: Mapped[int] = mapped_column(Integer, default=0)

    store: Mapped["Store"] = relationship(back_populates="agents")
