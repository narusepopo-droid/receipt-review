"""환경변수 및 설정 로딩"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://localhost/receipt_review"
    SECRET_KEY: str = "change-me-in-production"
    PHONE_ENC_KEY: str = "change-me-32-bytes-for-aes-256!!"
    PHONE_HMAC_KEY: str = "change-me-hmac-key-for-phone-hash"

    SERVER_URL: str = "https://review.placemaster.co.kr"
    UPLOAD_DIR: str = "./uploads"
    RECEIPT_IMAGE_DIR: str = "./data/receipts"
    RECEIPT_RAW_DIR: str = "./data/raw"

    BUSINESS_DAY_CUTOFF: str = "05:00"
    DEFAULT_PAPER_WIDTH: int = 576

    DEBUG: bool = False

    # 운영자 웹 로그인 (.env 로 바꿀 것)
    OPS_USERNAME: str = "admin"
    OPS_PASSWORD: str = "ReceiptReview2026!"

    # 세션 쿠키: 운영 서버(HTTPS)에서는 .env 에 SESSION_HTTPS_ONLY=true
    SESSION_HTTPS_ONLY: bool = False
    SESSION_MAX_AGE: int = 12 * 3600

    # 홍보 문자 (알리고) - 비어 있으면 모의 발송
    ALIGO_KEY: str = ""
    ALIGO_USER_ID: str = ""
    ALIGO_SENDER: str = ""          # 사전 등록된 발신번호
    ALIGO_OPTOUT_080: str = ""      # 080 무료수신거부 번호 (있으면 문구에 포함)
    SMS_COST_SMS: int = 20          # 건당 비용 (원)
    SMS_COST_LMS: int = 50

    # AI 리뷰 문장 (Phase 9) - 비어 있으면 기존 조합 방식
    ANTHROPIC_API_KEY: str = ""

    # 운영자 알림 받을 휴대폰 (에이전트 끊김 등). 알리고 키도 있어야 문자 발송
    OPS_ALERT_PHONE: str = ""

    # 외부 사이트에서 API 호출 허용 (가입 페이지 등)
    CORS_ORIGINS: str = "https://placemaster.co.kr,https://www.placemaster.co.kr,https://review.placemaster.co.kr"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# 편의를 위한 전역 인스턴스
settings = get_settings()
