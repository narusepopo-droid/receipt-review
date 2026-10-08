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
