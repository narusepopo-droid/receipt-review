"""
계정 서버 데이터 모델

회원(Account) ──< 매장(Store)                    (영수증리뷰처럼 매장 단위 상품용)
회원 ──< 이용권(License) >── 상품(Product) ──< 요금제(Plan)
이용권 ──< 이용권 기록(LicenseLog)               (결제·연장·운영자 변경 모두 기록)
회원 ──< 주문(Order) ──< 주문 항목(OrderItem)
회원 ──< 카드(BillingKey)                         (월 자동결제)
프로모션(Promotion), 설정(Setting), 알림 기록(NotificationLog)
"""
import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now_utc():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Stamp:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


# ───────────────────────── 회원 ─────────────────────────

class Account(Base, Stamp):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    firebase_uid: Mapped[Optional[str]] = mapped_column(String(128), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), default="")
    phone: Mapped[str] = mapped_column(String(20), default="")
    company: Mapped[str] = mapped_column(String(100), default="")
    biz_no: Mapped[str] = mapped_column(String(20), default="")
    is_operator: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    memo: Mapped[str] = mapped_column(Text, default="")
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    toss_customer_key: Mapped[str] = mapped_column(String(64), default=lambda: uuid.uuid4().hex)

    stores: Mapped[list["Store"]] = relationship(back_populates="account", order_by="Store.id")
    licenses: Mapped[list["License"]] = relationship(back_populates="account", order_by="License.id")


class Store(Base, Stamp):
    """매장 (영수증리뷰 등 매장 단위 상품)"""
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    biz_no: Mapped[str] = mapped_column(String(20), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(20), default="")
    review_store_id: Mapped[Optional[int]] = mapped_column(Integer)      # 영수증리뷰 서버의 매장 번호
    review_store_code: Mapped[Optional[str]] = mapped_column(String(20))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    account: Mapped[Account] = relationship(back_populates="stores")


# ───────────────────────── 상품·요금제 ─────────────────────────

class Unit(str, enum.Enum):
    ACCOUNT = "account"    # 계정당 1개 (플마)
    STORE = "store"        # 매장당 1개 (영수증리뷰)


class SignupPolicy(str, enum.Enum):
    APPROVAL = "approval"  # 가입 → 운영자 승인 → 사용
    PAYMENT = "payment"    # 가입 → 결제 → 사용


class Product(Base, Stamp):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)          # plma / receipt_review
    name: Mapped[str] = mapped_column(String(100))
    tagline: Mapped[str] = mapped_column(String(200), default="")
    unit: Mapped[Unit] = mapped_column(Enum(Unit), default=Unit.ACCOUNT)
    monthly_price: Mapped[int] = mapped_column(Integer, default=0)       # 정가 (월, 원)
    signup_policy: Mapped[SignupPolicy] = mapped_column(Enum(SignupPolicy), default=SignupPolicy.APPROVAL)
    download_url: Mapped[str] = mapped_column(String(500), default="")
    devices_per_license: Mapped[int] = mapped_column(Integer, default=1)  # PC 대수
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    plans: Mapped[list["Plan"]] = relationship(back_populates="product", order_by="Plan.sort")


class PlanKind(str, enum.Enum):
    FREE = "free"                  # 무료 (운영자 지급, 기본 무제한)
    MONTHLY = "monthly"            # 매월 자동결제 (약정 개월 동안)
    PREPAID = "prepaid"            # 일시불 N개월
    LIFETIME = "lifetime"          # 영구 (일시불)


class Plan(Base, Stamp):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[PlanKind] = mapped_column(Enum(PlanKind))
    months: Mapped[Optional[int]] = mapped_column(Integer)               # 일시불 기간 / 월결제 약정 개월 / 무료 기간(없으면 무제한)
    discount_pct: Mapped[int] = mapped_column(Integer, default=0)        # 정가 대비 할인율 (기간·일시불 할인 포함)
    lifetime_months: Mapped[int] = mapped_column(Integer, default=36)    # 영구권 가격 기준 개월
    price_override: Mapped[Optional[int]] = mapped_column(Integer)       # 직접 가격 지정 (있으면 우선)
    public: Mapped[bool] = mapped_column(Boolean, default=True)          # 점주 화면 판매 노출
    badge: Mapped[str] = mapped_column(String(30), default="")           # "추천", "최대 할인" 등
    sort: Mapped[int] = mapped_column(Integer, default=0)

    product: Mapped[Product] = relationship(back_populates="plans")


class Promotion(Base, Stamp):
    """프로모션: 쿠폰 코드 또는 자동 적용 (묶음 할인 포함)"""
    __tablename__ = "promotions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[Optional[str]] = mapped_column(String(40), unique=True)  # 없으면 조건 맞으면 자동 적용
    kind: Mapped[str] = mapped_column(String(20), default="percent")      # percent / amount / bundle
    value: Mapped[int] = mapped_column(Integer, default=0)                # % 또는 원
    product_codes: Mapped[list] = mapped_column(JSON, default=list)       # 비면 전체
    plan_kinds: Mapped[list] = mapped_column(JSON, default=list)          # 비면 전체
    min_products: Mapped[int] = mapped_column(Integer, default=1)         # bundle: 서로 다른 상품 N개 이상
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[Optional[int]] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ───────────────────────── 이용권 ─────────────────────────

class LicenseStatus(str, enum.Enum):
    PENDING = "pending"        # 승인·결제 대기
    ACTIVE = "active"
    SUSPENDED = "suspended"    # 운영자 정지 또는 기간 만료(유예 지남)
    CANCELLED = "cancelled"


class License(Base, Stamp):
    __tablename__ = "licenses"
    __table_args__ = (UniqueConstraint("account_id", "product_id", "store_id", name="uq_license_target"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    store_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stores.id"))
    plan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[LicenseStatus] = mapped_column(Enum(LicenseStatus), default=LicenseStatus.PENDING)
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))   # 없으면 무제한
    # 월 자동결제
    autopay: Mapped[bool] = mapped_column(Boolean, default=False)
    next_charge_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    commitment_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    autopay_cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    # PC 1대 제한
    device_id: Mapped[Optional[str]] = mapped_column(String(128))
    device_name: Mapped[str] = mapped_column(String(100), default="")
    device_bound_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    device_reset_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(Text, default="")

    account: Mapped[Account] = relationship(back_populates="licenses")
    product: Mapped[Product] = relationship()
    store: Mapped[Optional[Store]] = relationship()
    plan: Mapped[Optional[Plan]] = relationship()


class LicenseLog(Base):
    __tablename__ = "license_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    license_id: Mapped[int] = mapped_column(ForeignKey("licenses.id"), index=True)
    actor: Mapped[str] = mapped_column(String(120))       # system / operator:이메일 / owner / payment:주문번호
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


# ───────────────────────── 결제 ─────────────────────────

class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class Order(Base, Stamp):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: "RR" + uuid.uuid4().hex[:20].upper())
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    list_amount: Mapped[int] = mapped_column(Integer)          # 정가 합계
    discounts: Mapped[list] = mapped_column(JSON, default=list)  # [{"label":..., "amount":...}]
    amount: Mapped[int] = mapped_column(Integer)               # 결제 금액
    promo_code: Mapped[Optional[str]] = mapped_column(String(40))
    method: Mapped[str] = mapped_column(String(20), default="card")   # card(일시불) / billing(자동결제) / manual / free
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING)
    toss_payment_key: Mapped[Optional[str]] = mapped_column(String(200))
    receipt_url: Mapped[Optional[str]] = mapped_column(String(500))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    fail_reason: Mapped[str] = mapped_column(String(300), default="")

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", order_by="OrderItem.id")
    account: Mapped[Account] = relationship()


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    store_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stores.id"))
    license_id: Mapped[Optional[int]] = mapped_column(ForeignKey("licenses.id"))
    list_amount: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
    plan: Mapped[Plan] = relationship()
    store: Mapped[Optional[Store]] = relationship()


class BillingKey(Base, Stamp):
    """월 자동결제용 카드 (빌링키는 암호화 저장)"""
    __tablename__ = "billing_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    billing_key_enc: Mapped[str] = mapped_column(Text)
    card_company: Mapped[str] = mapped_column(String(40), default="")
    card_number: Mapped[str] = mapped_column(String(40), default="")    # 가린 번호
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ───────────────────────── 기타 ─────────────────────────

class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class NotificationLog(Base):
    __tablename__ = "notification_logs"
    __table_args__ = (UniqueConstraint("license_id", "kind", "ref", name="uq_notify_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    license_id: Mapped[int] = mapped_column(ForeignKey("licenses.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))      # d7 / d3 / d1 / expired / charged / charge_failed
    ref: Mapped[str] = mapped_column(String(40))       # 만료일 등 (같은 만료일에 한 번만)
    message: Mapped[str] = mapped_column(Text, default="")
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
