"""Phase 9 선택 기능 설정·데이터 (기존 테이블을 바꾸지 않도록 새 테이블)"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class StoreOptions(Base):
    """매장별 선택 기능 켜기/끄기"""
    __tablename__ = "store_options"

    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), primary_key=True)
    phone_verify: Mapped[bool] = mapped_column(Boolean, default=False)    # 휴대폰 인증번호
    ai_text: Mapped[bool] = mapped_column(Boolean, default=False)         # AI 문장 다양화
    review_check: Mapped[bool] = mapped_column(Boolean, default=False)    # 리뷰 등록 자동 확인
    naver_place_id: Mapped[Optional[str]] = mapped_column(String(30))     # 리뷰 확인용 플레이스 번호


class PhoneOtp(Base, TimestampMixin):
    """휴대폰 인증번호 (번호·코드는 해시로만 저장)"""
    __tablename__ = "phone_otps"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ReviewCheck(Base, TimestampMixin):
    """네이버 공개 리뷰에서 우리 문구가 확인된 세션"""
    __tablename__ = "review_checks"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True, nullable=False)
    similarity: Mapped[int] = mapped_column(Integer, default=0)           # %
    review_excerpt: Mapped[Optional[str]] = mapped_column(Text)


class PhraseUsage(Base):
    """매장별 문장 사용 횟수 — 한 바퀴 다 쓰기 전에는 같은 문장을 다시 쓰지 않기 위함"""
    __tablename__ = "phrase_usage"

    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), primary_key=True)
    phrase_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
